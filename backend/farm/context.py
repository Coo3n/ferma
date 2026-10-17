"""Контекст сценария — то, что получает каждый сценарий в аргументе `ctx`.

Всё, что нужно для написания сценария, доступно здесь: действия над устройством,
ожидания, логирование, скриншоты, и `ctx.d` — сырой клиент uiautomator2 для
случаев, когда обёрток не хватает.
"""
from __future__ import annotations

import inspect
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from . import adb, config, control, deviations as dv, guards, obstacle, resolve
from .devices import pool as u2pool
from .ui import tree

log = logging.getLogger("farm.ctx")

# Глубже пяти блоков сценарий перестаёт читаться, а стек вызовов в
# сообщении об ошибке — помещаться на экран.
MAX_BLOCK_DEPTH = 5

# Общий выход с незнакомого экрана. Порядок неслучаен: back дешевле всего и
# работает чаще прочего, крестик — последним, он чаще всего неоднозначен.
# None означает клавишу «Назад», остальное — селекторы кнопок.
ESCAPE_STEPS = (
    None,
    {"textMatches": "(?i)(закрыть|close|не сейчас|not now)"},
    {"textMatches": "(?i)(пропустить|skip|позже|later|отмена|cancel)"},
    {"descriptionMatches": "(?i)(закрыть|close|dismiss)"},
)
# Два круга, а не три: третий повторял бы то же самое. Второй нужен ради
# наложенных друг на друга диалогов. Таймауты короткие — выход это последняя
# попытка перед падением прогона, и стоить он должен секунды, а не десятки:
# на промахе якоря он срабатывает на каждом из двадцати устройств.
# Шаг ожидания элемента. Ждём кусками, а не одним `wait(timeout)`: внутри
# ожидания uiautomator2 отмену не спросить, и задача висела бы до конца
# таймаута после нажатия «отменить».
FIND_SLICE = 1.0

ESCAPE_ROUNDS = 2
ESCAPE_PROBE = 0.4      # сек на поиск кнопки выхода
ESCAPE_RECHECK = 0.3    # сек на пересверку, выбрались ли

# Решения, которые человек принимает над остановленной задачей. Живут здесь, а
# не в runner: их обязаны знать все три стороны — шаг, который спрашивает,
# очередь, которая ждёт ответа, и API, которое ответ принимает.
HOLD_RETRY = "retry"    # экран поправлен руками, попробуй шаг ещё раз
HOLD_SKIP = "skip"      # шаг не критичный, иди дальше без него
HOLD_DROP = "drop"      # роняй задачу, как было бы без остановки
HOLD_GO = "go"          # только для «вслепую»: продолжить как есть
HOLD_DECISIONS = (HOLD_RETRY, HOLD_SKIP, HOLD_DROP, HOLD_GO)

HOLD_WORDS = {HOLD_RETRY: "повторить шаг", HOLD_SKIP: "пропустить шаг",
              HOLD_DROP: "уронить задачу", HOLD_GO: "продолжить как есть"}


# Признаки экрана из системного интерфейса (шторка, статус-бар) есть на любом
# экране: якорь только на них проверяет не экран, а наличие статус-бара.
SYSTEM_UI_PREFIXES = ("com.android.systemui", "android:id/")


def is_weak_anchor(features) -> bool:
    """Все признаки — системный интерфейс, экран приложения ими не опознать."""
    def system(f):
        text = " ".join(str(v) for v in (f or {}).values())
        return any(p in text for p in SYSTEM_UI_PREFIXES)
    return bool(features) and all(system(f) for f in features)


class Cancelled(Exception):
    """Задача отменена пользователем."""


class StepFailed(AssertionError):
    """Шаг сценария не выполнился — сценарий останавливается с артефактами.

    `miss` — JSON цели, которую искал промахнувшийся click_target; у любого
    другого падения пуст. Живёт на самом исключении, а не на контексте: так
    цель прошлого клика не припишется чужому падению.
    """
    miss: str = ""


def _takes_miss(fn) -> bool:
    return _takes(fn, "miss")


def _takes(fn, name: str) -> bool:
    try:
        ps = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == name or p.kind == p.VAR_KEYWORD for p in ps)


def _miss_json(sel, text, img, at) -> str:
    """Цель промахнувшегося click_target — нормализованный JSON-безопасный вид."""
    def lst(v):
        if v is None:
            return []
        return list(v) if isinstance(v, (list, tuple)) else [v]
    try:
        return json.dumps({
            "sel": [d for d in lst(sel) if isinstance(d, dict)],
            "text": [str(t) for t in lst(text)],
            "img": Path(str(img)).name if img else "",
            "at": [float(c) for c in at] if at else [],
        }, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 — цель для показа не должна ломать падение
        return ""


# Ключи селектора, которые можно прислать в sel, и тип значения. Список =
# пересечение того, что панель умеет писать (farm/ui/selectors.py: resourceId,
# description, text, textContains, className, instance; farm/obstacle.py:
# resourceId, textContains, descriptionContains), и того, что принимает
# uiautomator2.Selector. Ключи библиотеки, которых панель не пишет, лишние.
# Неизвестный ключ иначе упал бы уже внутри задачи, после «повторить».
SEL_KEY_TYPES: dict = {
    **dict.fromkeys((
        "text", "textContains", "textStartsWith",
        "className", "description", "descriptionContains",
        "descriptionStartsWith", "packageName", "resourceId"), str),
    **dict.fromkeys(("index", "instance"), int),
    "clickable": bool,
}
# Только то, что генерирует панель, и точные родственники. `*Matches` не
# пускаем: это регулярка от клиента, исполняемая на устройстве (ReDoS); прочие
# bool-флаги нигде в сценариях/панели не встречаются (YAGNI).
MAX_SEL_ENTRIES = 8
# Значения берутся из выбранного в пикере узла: длинный text/description
# реален, 500 символов отвергали бы честный селектор.
MAX_SEL_VALUE_LEN = 2000
MAX_TEXT_ENTRIES = 20
_TYPE_WORD = {str: "строкой", int: "целым числом", bool: "true/false"}


def _check_sel(v) -> list:
    if not isinstance(v, list) or not all(isinstance(d, dict) for d in v):
        raise ValueError("sel — список словарей")
    if len(v) > MAX_SEL_ENTRIES:
        raise ValueError(f"sel: не больше {MAX_SEL_ENTRIES} селекторов")
    for d in v:
        if not d:
            raise ValueError("sel: селектор не может быть пустым")
        for k, val in d.items():
            want = SEL_KEY_TYPES.get(k)
            if want is None:
                raise ValueError(f"sel: неизвестный ключ селектора «{k}»")
            # bool — подкласс int: instance=True не должен проходить как 1
            ok = (isinstance(val, int) and not isinstance(val, bool)
                  if want is int else isinstance(val, want))
            if not ok:
                raise ValueError(f"sel: «{k}» должно быть {_TYPE_WORD[want]}")
            if want is str and len(val) > MAX_SEL_VALUE_LEN:
                raise ValueError(
                    f"sel: значение «{k}» длиннее {MAX_SEL_VALUE_LEN} символов")
    return v


def normalize_target(raw) -> dict:
    """Проверить исправленную человеком цель click_target. ValueError — не годится.

    Пропускает только ключи sel/text/img/at нужной формы; img — голое имя файла
    (путь пришёл бы от клиента, а читать по нему шаблон нельзя); at — доли
    экрана в [0, 1]. Пустое или None — «патча нет».
    """
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("цель должна быть объектом")
    лишние = set(raw) - {"sel", "text", "img", "at"}
    if лишние:
        raise ValueError(f"неизвестные поля цели: {', '.join(sorted(map(str, лишние)))}")
    out: dict = {}
    if "sel" in raw:
        v = raw["sel"]
        out["sel"] = _check_sel(v)
    if "text" in raw:
        v = raw["text"]
        if not isinstance(v, list) or not all(isinstance(t, str) for t in v):
            raise ValueError("text — список строк")
        if len(v) > MAX_TEXT_ENTRIES:
            raise ValueError(f"text: не больше {MAX_TEXT_ENTRIES} строк")
        if any(len(t) > MAX_SEL_VALUE_LEN for t in v):
            raise ValueError(f"text: строка длиннее {MAX_SEL_VALUE_LEN} символов")
        out["text"] = v
    if "img" in raw:
        v = raw["img"]
        if (not isinstance(v, str) or not v or v == ".." or "/" in v
                or "\\" in v or ".." in v or "\x00" in v or ":" in v
                or len(v) > 255):
            raise ValueError("img — имя файла без пути (до 255 символов, без «:»)")
        out["img"] = v
    if "at" in raw:
        v = raw["at"]
        ok = (isinstance(v, (list, tuple)) and len(v) == 2 and all(
            isinstance(c, (int, float)) and not isinstance(c, bool)
            and 0 <= c <= 1 for c in v))   # NaN не проходит сравнение
        if not ok:
            raise ValueError("at — две доли экрана от 0 до 1")
        out["at"] = [float(c) for c in v]
    # цель из одних пустых частей resolve не разберёт (сырой ValueError в задаче)
    if not (out.get("sel") or out.get("text") or out.get("img") or out.get("at")):
        raise ValueError("цель пуста: нужен sel, text, img или at")
    return out


class DeviceContext:
    def __init__(
            self,
            serial: str,
            params: dict[str, Any] | None = None,
            logger: Callable[[str], None] | None = None,
            cancel_check: Callable[[], bool] | None = None,
            artifacts_dir: Path | None = None,
            device_name: str = "",
            scenario_assets: Path | None = None,
            job_id: str = "",
            scenario_key: str = "",
            scenario_name: str = "",
            hold: Callable[[str], str] | None = None,
            take_target_patch: Callable[[], dict | None] | None = None,
    ) -> None:
        self.serial = serial
        self.device_name = device_name or serial
        # Чем подписывать отклонения: без задачи и сценария запись сообщает
        # о беде, но не говорит, где её искать.
        self.job_id = job_id
        self.scenario_key = scenario_key
        self.scenario_name = scenario_name or scenario_key
        self.params = params or {}
        self._logger = logger or (lambda m: log.info("[%s] %s", serial, m))
        self._cancel_check = cancel_check or (lambda: False)
        self.artifacts_dir = artifacts_dir
        self.scenario_assets = scenario_assets
        # Как спросить человека, что делать с промахнувшимся шагом. Подставляет
        # очередь: только она может остановить задачу, не отпустив устройство.
        # None означает «спрашивать некому» — шаг падает, как раньше.
        self._hold = hold
        # Исправленная цель от человека: отдаёт и забывает (один раз на ответ).
        self._take_target_patch = take_target_patch
        self.started_at = time.time()
        self._shot_n = 0
        self._escape_n = 0
        self._lost_n = 0
        self._holds = 0
        # Сторож долгих циклов (on_track): когда смотрели, что видели, сколько раз подряд.
        self._watch_at = 0.0
        self._watch_sig = ""
        self._watch_same = 0
        self._layer_shots: set[str] = set()   # подписи LAYER, уже снятые
        self.human = False
        # Замедление прогона для отладки: 1 — как есть, 0.5 — вдвое медленнее.
        # Растягивает паузы и добавляет «подумать» перед каждым жестом.
        self.speed = 1.0
        # Колбэк отметки статуса текущего шага («retried», «skipped»): даёт runner.
        self.step_mark: Callable[[str], None] | None = None
        self.settle = True
        self._stack: list[str] = []   # цепочка вызванных блоков, см. run()
        self._guards = guards.GuardEngine()

    # ------------------------------------------------------------------ базовое
    def log(self, message: str) -> None:
        """Внутри блока строки идут с отступом — иначе в журнале каша:
        непонятно, чей это шаг, вызывающего сценария или вызванного."""
        self._logger("  " * len(self._stack) + str(message))

    def check_cancel(self) -> None:
        if self._cancel_check():
            raise Cancelled("отменено пользователем")

    def sleep(self, seconds: float) -> None:
        """Пауза с проверкой отмены каждые 0.2 с."""
        if self.speed and self.speed < 1:
            seconds = seconds / self.speed
        end = time.time() + seconds
        while time.time() < end:
            self.check_cancel()
            time.sleep(min(0.2, end - time.time()))

    def fail(self, message: str, miss: str = "") -> None:
        e = StepFailed(message)
        e.miss = miss
        raise e

    def _stuck(self, что: str, miss: str = "", kind: str = "", obstacle: str = "",
               refusal: str = HOLD_DROP) -> str:
        """Шаг промахнулся — спросить человека, что делать. Вернуть решение.

        Останавливаться имеет смысл только пока экран на телефоне ещё тот
        самый: отпущенное устройство тут же забирает следующая задача, и
        показывать человеку становится нечего. Поэтому останавливает не
        интерфейс «потом», а сам шаг — здесь и сейчас.

        Ответ DROP означает «веди себя как раньше»: без включённой остановки
        (`FARM_HOLD=0`), без очереди (сценарий гоняют из теста или из кода) и
        после исчерпания потолка остановок шаг падает ровно как до появления
        этого механизма.
        """
        # refusal — ответ, когда человек не отвечал вовсе (спросить некого,
        # потолок, сорванный вопрос): DROP для промаха шага, «идти дальше» для
        # сторожа долгого цикла — он и раньше листал до конца.
        if self._hold is None or not config.HOLD:
            return refusal
        if self._holds >= config.HOLD_MAX_PER_JOB:
            self.log(f"остановок в этой задаче уже {self._holds}, "
                     f"потолок исчерпан — дальше без вопросов")
            return refusal
        self.check_cancel()
        self._holds += 1
        try:
            # miss/kind/obstacle отдаём только тем колбэкам, что их принимают:
            # одноаргументный hold (тесты, чужой код) работает как раньше.
            доп = {k: v for k, v in (("miss", miss), ("kind", kind), ("obstacle", obstacle))
                   if v and _takes(self._hold, k)}
            решение = self._hold(что, **доп)
        except Cancelled:
            raise      # отмена задачи — не «решение человека»
        except Exception as e:  # noqa: BLE001 — сорванный вопрос не меняет исход
            self.log(f"спросить человека не удалось: {e}")
            return refusal
        # Отмена будит остановленную задачу тем же событием, что и решение, —
        # иначе она проспала бы отмену до конца ожидания. Поэтому здесь
        # проверяем заново: «разбудили» и «ответили» это не одно и то же.
        self.check_cancel()
        if решение not in HOLD_DECISIONS:
            self.log(f"непонятное решение «{решение}» — роняю задачу")
            return HOLD_DROP
        self.log(f"решение человека: {HOLD_WORDS[решение]}")
        return решение

    def _ask_blind(self, что: str) -> str:
        """Шаг собирается пройти вслепую — спросить человека, что делать.

        Метка «blind» уже стоит на шаге: по ней очередь понимает, что это не
        промах, и предлагает «продолжить как есть». Не спрашиваем (и идём как
        раньше) без очереди, при `FARM_HOLD=0` или `FARM_HOLD_BLIND=0`; сорванный
        вопрос и непонятный ответ тоже не роняют задачу — падает только тот,
        кто сам сказал «уронить». Потолок остановок на задачу не тратим:
        сценарий с десятком слабых якорей не должен исчерпать его на них.
        """
        if self._hold is None or not config.HOLD or not config.HOLD_BLIND:
            return HOLD_GO
        self.check_cancel()
        try:
            решение = self._hold(что)
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            self.log(f"спросить человека не удалось: {e} — иду дальше вслепую")
            return HOLD_GO
        self.check_cancel()
        if решение not in HOLD_DECISIONS:
            self.log(f"непонятное решение «{решение}» — иду дальше вслепую")
            return HOLD_GO
        self.log(f"решение человека: {HOLD_WORDS[решение]}")
        return решение

    def humanize(self) -> None:
        """Человечный режим: разброс точек тапа, кривые свайпы, посимвольная
        печать и микропаузы перед действиями. Включается на весь сценарий."""
        self.human = True

    def pause(self, lo: float = 0.4, hi: float = 1.5) -> None:
        """Случайная пауза «подумал и нажал»."""
        self.sleep(control.humanize.pause_time(lo, hi))

    def _pre_action(self) -> None:
        """Микропауза перед жестом в человечном режиме."""
        if self.human:
            self.sleep(control.humanize.pause_time(0.15, 0.7))
        if self.speed and self.speed < 1:
            # sleep() растягивает на 1/speed: при 0.5 это секунда «на подумать».
            self.sleep((1 - self.speed))

    def _settle(self) -> None:
        """Дождаться, пока экран дорисуется, прежде чем искать цель."""
        if self.settle and config.SETTLE:
            control.wait_stable(self.serial)

    @property
    def d(self):
        """Сырой клиент uiautomator2. None, если подключиться не удалось."""
        return u2pool.get(self.serial)

    def require_u2(self):
        d = self.d
        if d is None:
            raise StepFailed("uiautomator2 недоступен на этом устройстве")
        return d

    @property
    def size(self) -> tuple[int, int]:
        return control.size(self.serial)

    # ------------------------------------------------------------------ ввод
    def tap(self, x: float, y: float) -> None:
        self.check_cancel()
        self._pre_action()
        if self.human:
            control.humanize.tap(self.serial, x, y)
        else:
            control.tap(self.serial, x, y)

    def long_tap(self, x: float, y: float, duration: float = 0.8) -> None:
        self.check_cancel()
        self._pre_action()
        control.long_tap(self.serial, x, y, duration)

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration: float = 0.25) -> None:
        self.check_cancel()
        self._pre_action()
        if self.human:
            control.humanize.swipe(self.serial, x1, y1, x2, y2, duration)
        else:
            control.swipe(self.serial, x1, y1, x2, y2, duration)

    def scroll_down(self, times: int = 1) -> None:
        for _ in range(times):
            self.swipe(0.5, 0.75, 0.5, 0.3, 0.25)
            self.sleep(0.3)

    def scroll_up(self, times: int = 1) -> None:
        for _ in range(times):
            self.swipe(0.5, 0.3, 0.5, 0.75, 0.25)
            self.sleep(0.3)

    def type(self, value: str, clear: bool = False) -> None:
        self.check_cancel()
        self._settle()
        self._pre_action()
        if self.human:
            control.humanize.send_text(self.serial, value, clear=clear)
        else:
            control.text(self.serial, value, clear=clear)

    def key(self, name: str) -> None:
        self.check_cancel()
        control.key(self.serial, name)

    def back(self) -> None:
        self.key("back")

    def home(self) -> None:
        self.key("home")

    def unlock(self, pin: str | None = None) -> None:
        control.unlock(self.serial, pin)

    # ------------------------------------------------------------------ поиск элементов
    def find(self, timeout: float = 10, **selector):
        """Найти элемент по селектору uiautomator2: text=, resourceId=, description=, ...

        Возвращает объект элемента или None.
        """
        d = self.require_u2()
        el = d(**selector)
        # Ожидание нарезано на куски: `el.wait(10)` не прерывается изнутри, и
        # отмена ждала бы конца таймаута, хотя человек уже нажал «отменить».
        end = time.time() + timeout
        while True:
            self.check_cancel()
            кусок = min(FIND_SLICE, max(0.0, end - time.time()))
            if el.wait(timeout=кусок):
                return el
            if time.time() >= end:
                return None

    def click(self, timeout: float = 10, scroll: bool = True, **selector) -> None:
        """Найти и нажать. Не нашлось на экране — проскроллить к элементу.

        Падает с понятным сообщением, если элемента нет и после прокрутки.
        Или не падает, а ждёт человека — см. `_stuck`.
        """
        беда = f"не найден элемент {selector} за {timeout} с"
        while True:
            self.check_cancel()
            self._settle()
            el = self.find(timeout=timeout, **selector)
            if el is None and scroll:
                el = self._scroll_to(**selector)
            if el is None and self._rescue():
                el = self.find(timeout=5, **selector)
                if el is None and scroll:
                    el = self._scroll_to(**selector)
            if el is not None:
                self._click_el(el)
                return
            решение = self._stuck(беда)
            if решение == HOLD_RETRY:
                continue
            if решение == HOLD_SKIP:
                return
            self.fail(беда)

    def click_any(self, *selectors: dict, timeout: float = 10) -> None:
        """Цепочка селекторов из конструктора: нажимается первый найденный.

        Запасные селекторы спасают на другой прошивке или локали, где
        основной не совпал. Общий timeout делится на быстрые круги по всем
        кандидатам, затем последняя попытка — прокрутка к каждому.
        """
        беда = f"не найден ни один из селекторов {list(selectors)} за {timeout} с"
        while True:
            self.check_cancel()
            self._settle()
            if self._click_first(selectors, timeout):
                return
            решение = self._stuck(беда)
            if решение == HOLD_RETRY:
                continue
            if решение == HOLD_SKIP:
                return
            self.fail(беда)

    def _click_first(self, selectors: tuple, timeout: float) -> bool:
        """Один круг поиска цепочки: быстрые попытки, прокрутка, стражи."""
        end = time.time() + timeout
        while True:
            for sel in selectors:
                el = self.find(timeout=1.5, **sel)
                if el is not None:
                    self._click_el(el)
                    return True
            if time.time() >= end:
                break
        for sel in selectors:
            el = self._scroll_to(**sel)
            if el is not None:
                self._click_el(el)
                return True
        if self._rescue():
            for sel in selectors:
                el = self.find(timeout=1.5, **sel)
                if el is not None:
                    self._click_el(el)
                    return True
        return False

    def _scroll_to(self, **selector):
        """Прокрутить список к элементу — экран мог оказаться меньше макета."""
        d = self.d
        if d is None:
            return None
        try:
            d(scrollable=True).scroll.to(**selector)
        except Exception:  # noqa: BLE001 — нет прокручиваемого контейнера
            return None
        return self.find(timeout=2, **selector)

    def _click_el(self, el) -> None:
        """Нажать найденный элемент. В человечном режиме — не в центр."""
        self._pre_action()
        if self.human:
            try:
                b = el.info["bounds"]
                w, h = self.size
                x, y = control.humanize.point_in(
                    b["left"] / w, b["top"] / h, b["right"] / w, b["bottom"] / h)
                control.humanize.tap(self.serial, x, y)
                return
            except Exception:  # noqa: BLE001 — info недоступен, жмём как обычно
                pass
        el.click()

    def click_if_exists(self, timeout: float = 2, **selector) -> bool:
        el = self.find(timeout=timeout, **selector)
        if el is None:
            return False
        el.click()
        return True

    def exists(self, timeout: float = 2, **selector) -> bool:
        return self.find(timeout=timeout, **selector) is not None

    def wait_gone(self, timeout: float = 10, **selector) -> bool:
        d = self.require_u2()
        return d(**selector).wait_gone(timeout=timeout)

    def set_text(self, value: str, timeout: float = 10, **selector) -> None:
        беда = f"не найдено поле ввода {selector}"
        while True:
            self.check_cancel()
            self._settle()
            el = self.find(timeout=timeout, **selector)
            if el is None and self._rescue():
                el = self.find(timeout=5, **selector)
            if el is not None:
                break
            решение = self._stuck(беда)
            if решение == HOLD_RETRY:
                continue
            if решение == HOLD_SKIP:
                return
            self.fail(беда)
        el.click()
        self.sleep(0.3)
        el.set_text(value)

    def text_on_screen(self, needle: str) -> bool:
        return needle in self.dump_hierarchy()

    # ------------------------------------------------------------------ многослойные цели
    def screen_bytes(self) -> bytes:
        """Свежий JPEG экрана для слоёв зрения."""
        return control.screenshot(self.serial, quality=85)

    def asset(self, name: str) -> tuple[bytes | None, float]:
        """Байты ассета записи и базовый масштаб (ширина сейчас ÷ при записи)."""
        if not self.scenario_assets:
            return None, 1.0
        path = Path(self.scenario_assets) / name
        if not path.is_file():
            return None, 1.0
        base = 1.0
        try:
            meta = json.loads(
                (Path(self.scenario_assets) / "meta.json").read_text("utf-8"))
            width = float(meta.get("screen_width") or 0)
            if width > 0:
                base = self.size[0] / width
        except (OSError, ValueError):
            pass
        return path.read_bytes(), base

    def click_target(self, sel=None, text=None, img=None, at=None,
                     timeout: float = 10) -> None:
        """Клик по многослойной цели: селекторы → текст → OCR → шаблон → точка.

        После «повторить» человек мог приложить исправленную цель: заменяются
        ровно присланные ключи, и дальше все попытки ЭТОГО вызова идут с ней
        (даже если следующая остановка пройдёт без нового патча). Патч живёт в
        локальных переменных — следующий click_target получит свои аргументы.
        """
        def _беда():
            return (f"цель не найдена ни одним слоем: "
                    f"sel={sel} text={text} img={img} at={at}")
        беда = _беда()
        while True:
            self.check_cancel()
            self._settle()
            hit = resolve.resolve(self, sel=sel, text=text, img=img, at=at,
                                  timeout=timeout)
            if hit is None and self._rescue():
                hit = resolve.resolve(self, sel=sel, text=text, img=img, at=at,
                                      timeout=5)
            if hit is not None and hit.layer == "point":
                # Ни один слой, кроме сохранённых координат, цель не нашёл:
                # тап уйдёт «в то место, где она была». Спрашиваем ДО тапа —
                # пока на телефоне тот экран, на котором это выяснилось.
                if self.step_mark:
                    self.step_mark("blind")
                вопрос = ("цель не найдена ни селектором, ни текстом, ни картинкой — "
                          "тап вслепую по сохранённым координатам. Продолжить?")
                self.log(вопрос)
                решение = self._ask_blind(вопрос)
                if решение == HOLD_RETRY:
                    continue
                if решение == HOLD_SKIP:
                    return
                if решение == HOLD_DROP:
                    self.fail(беда, _miss_json(sel, text, img, at))
                break
            if hit is not None:
                break
            miss = _miss_json(sel, text, img, at)
            решение = self._stuck(беда, miss)
            if решение == HOLD_RETRY:
                патч = self._take_target_patch() if self._take_target_patch else None
                if патч:
                    sel = патч.get("sel", sel)
                    text = патч.get("text", text)
                    img = патч.get("img", img)
                    at = патч.get("at", at)
                    беда = _беда()
                    self.log(f"цель заменена человеком: {', '.join(патч)}")
                continue
            if решение == HOLD_SKIP:
                return
            self.fail(беда, miss)
        if hit.layer == "point":
            self.log("тап вслепую по координатам: результат не проверен")
        if hit.layer != "selector":
            self.log(f"цель найдена слоем «{hit.layer}» ({hit.detail}) — "
                     f"селекторы не совпали, пора обновить сценарий")
            # Тихая поломка: сценарий не упал, и без записи об этом узнают
            # только когда отвалится и последний слой — то есть в самый
            # неудобный момент.
            # Кадр — только при первом попадании подписи на этом устройстве:
            # отклонения сливаются по подписи, а цикл с устаревшим селектором
            # иначе писал бы по картинке на каждый клик.
            подпись = f"{hit.layer}|{sel}"
            shot = ""
            if подпись not in self._layer_shots:
                self._layer_shots.add(подпись)
                shot = self._deviation_shot("layer")
            try:
                dv.deviations.record(
                    kind=dv.LAYER,
                    title=f"селектор устарел, спас слой «{hit.layer}»",
                    detail=f"Цель нашлась не селектором, а слоем «{hit.layer}» "
                           f"({hit.detail}). Сценарий доехал, но запас прочности "
                           f"израсходован — поправьте селектор шага.",
                    device_name=self.device_name,
                    job_id=self.job_id,
                    scenario_key=self.scenario_key,
                    scenario_name=self.scenario_name,
                    shot=shot,
                    signature=подпись,
                )
            except Exception as e:  # noqa: BLE001 — запись не роняет прогон
                self.log(f"отклонение об устаревшем селекторе не записалось: {e}")
        self.tap(hit.x, hit.y)

    def expect_screen(self, name: str, any: list | None = None,
                      timeout: float = 10) -> None:
        """Якорь: убедиться, что мы на экране «name», прежде чем действовать.

        Чужой экран ловится здесь — до клика, а не через три шага тапов
        в пустоту.
        """
        features = list(any or [])
        if not features:
            raise ValueError(f"expect_screen({name!r}) без признаков экрана")
        if is_weak_anchor(features):
            # Совпадёт на любом экране, в том числе на заставке: честно
            # говорим, что экран не проверен, и хотя бы ждём, пока он устаканится.
            беда = (f"якорь «{name}» опирается только на системную панель — экран "
                    f"приложения не проверен. Посмотрите на телефон: это нужный экран?")
            self.log(беда)
            if self.step_mark:
                self.step_mark("blind")
            self._settle()
            решение = self._ask_blind(беда)
            while решение == HOLD_RETRY:      # «подождать»: экран ещё грузится
                self._settle()
                решение = self._ask_blind(беда)
            if решение == HOLD_SKIP:
                return
            if решение == HOLD_DROP:
                self.fail(f"человек остановил сценарий на слабом якоре «{name}»")
        while True:
            self.check_cancel()
            if self._wait_features(features, timeout):
                return
            if self._rescue() and self._wait_features(features, 5):
                return
            # Стражи знают только объявленные преграды. Незаявленную пробуем
            # закрыть вслепую — это дешевле, чем падение всего прогона.
            if self.escape(lambda: self._wait_features(features, ESCAPE_RECHECK)):
                return
            try:
                app = self.current_app()
            except Exception:  # noqa: BLE001
                app = "?"
            texts = ", ".join(self._screen_texts())
            беда = f"ожидал экран «{name}», вижу {app}: [{texts}]"
            # Спрашиваем до артефактов: на «повторить» они не понадобятся, а
            # эталон с актуальным кадром стоит секунды на каждом устройстве.
            решение = self._stuck(беда)
            if решение == HOLD_RETRY:
                continue
            if решение == HOLD_SKIP:
                return
            self._expect_artifacts(name)
            self.fail(беда)

    def which_screen(self, варианты: dict, timeout: float = 10,
                     default: str = "", report: bool = True) -> str:
        """Куда мы попали: имя первой совпавшей ветки или `default`.

        Развилка, а не проверка. `expect_screen` отвечает на «я обязан быть
        тут» и падает, если нет; `which_screen` — на «где я?» и не падает
        никогда: на живой ферме один и тот же шаг встречает то онбординг, то
        пейволл, то сразу каталог, и это норма, а не сбой.

        Порядок вариантов значим: побеждает первый совпавший, поэтому узкие
        ветки объявляют раньше широких. Внутри ветки признаки — «любой из»,
        как в `expect_screen(any=...)`.

        `report=True` означает «я перечислил всё, что бывает», и несовпадение
        ни с чем записывается отклонением: появилась ветка, которой ферма не
        знает. Если же «никакая» — это штатный случай (необязательный пейволл,
        которого обычно нет), передают `report=False`, иначе каждый нормальный
        прогон писал бы отклонение.
        """
        if not варианты:
            raise ValueError("which_screen без вариантов")
        end = time.time() + timeout
        while True:
            # timeout=0 — один быстрый круг по признакам ветки: ждать здесь
            # должен внешний цикл, иначе первая ветка съела бы весь таймаут и
            # до остальных дело дошло бы только после него.
            for имя, features in варианты.items():
                self.check_cancel()
                if self._wait_features(list(features or []), 0):
                    self.log(f"развилка: ветка «{имя}»")
                    return имя
            if time.time() >= end:
                break
        # Перехватчик поверх экрана скрывает все ветки разом, поэтому стражам
        # дают ход до того, как признать развилку незнакомой.
        if self._rescue():
            for имя, features in варианты.items():
                if self._wait_features(list(features or []), 0):
                    self.log(f"развилка: ветка «{имя}» (после стражей)")
                    return имя
        self.log(f"развилка: ни одна из ветвей не совпала "
                 f"({', '.join(варианты)}) — иду дальше как «{default}»")
        if report:
            self._report_branch(варианты, default)
        return default

    def _deviation_shot(self, имя: str) -> str:
        """Снимок для отклонения: имя файла или "" — шаг из-за фото не ломаем.

        Без папки артефактов задачи снимать некуда: общий корень маршрут
        артефактов задачи не отдаёт, а вернуть можно лишь голое имя.
        """
        if not self.artifacts_dir:
            return ""
        try:
            return Path(self.screenshot(имя)).name
        except Exception as e:  # noqa: BLE001
            self.log(f"фото отклонения не снялось: {e}")
            return ""

    def _report_branch(self, варианты: dict, default: str) -> None:
        """Развилка не узнала экран — значит, у сюжета появилась ветка, которой
        никто не описал. Сам прогон это не роняет, поэтому по журналу задач
        такого не видно вовсе: узнать можно только отсюда."""
        texts = ", ".join(self._screen_texts())
        try:
            app = self.current_app()
        except Exception:  # noqa: BLE001
            app = "?"
        shot = self._deviation_shot("branch")
        try:
            dv.deviations.record(
                kind=dv.BRANCH,
                title=f"незнакомая ветка: вижу {app}: [{texts}]",
                detail="Ни одна из описанных ветвей не совпала: "
                       f"{', '.join(варианты)}. Сценарий пошёл дальше как "
                       f"«{default}». Допишите ветку для этого экрана — или "
                       "снимите у шага галку «жаловаться», если «никакая» тут "
                       "штатный случай.",
                device_name=self.device_name,
                job_id=self.job_id,
                scenario_key=self.scenario_key,
                scenario_name=self.scenario_name,
                # Подпись — набор объявленных ветвей плюс то, что видим:
                # одна и та же непокрытая развилка на двадцати устройствах
                # должна быть одной строкой, а разные развилки — разными.
                shot=shot,
                signature=f"branch|{sorted(варианты)}|{texts}",
            )
        except Exception as e:  # noqa: BLE001 — запись не роняет прогон
            self.log(f"отклонение о незнакомой ветке не записалось: {e}")

    def _wait_features(self, features: list, timeout: float) -> bool:
        end = time.time() + timeout
        while True:
            for feature in features:
                self.check_cancel()
                if self.exists(timeout=0.5, **feature):
                    return True
            if time.time() >= end:
                return False

    def _screen_texts(self, limit: int = 5) -> list:
        """Верхние тексты экрана — чтобы сообщение об ошибке было читаемым."""
        try:
            w, h = self.size
            nodes = tree.parse(self.dump_hierarchy(), w, h)
        except Exception:  # noqa: BLE001
            return []
        out = []
        for node in nodes:
            label = (node.text or node.description or "").strip()
            if label and label not in out:
                out.append(label)
            if len(out) >= limit:
                break
        return out

    def _expect_artifacts(self, name: str) -> None:
        """Пара expected/actual в артефакты — расхождение видно глазами."""
        try:
            self.screenshot(f"actual_{name}")
        except Exception:  # noqa: BLE001
            pass
        data, _ = self.asset(f"expect_{name}.png")
        if data and self.artifacts_dir:
            try:
                (Path(self.artifacts_dir) / f"expected_{name}.png").write_bytes(data)
                self.log(f"эталон экрана «{name}» приложен к артефактам")
            except OSError:
                pass

    # ------------------------------------------------------------------ приложения
    def launch_app(self, package: str, activity: str | None = None, stop_first: bool = False,
                   wait: float = 15.0) -> None:
        """Запустить приложение и дождаться, пока оно выйдет на экран.

        `wait` — потолок ожидания появления пакета, а не слепая пауза:
        быстрый телефон продолжит через секунду, медленный получит время.
        Если пакет так и не вышел на экран, сценарий идёт дальше — упадёт
        первый же click с внятным сообщением, а не сам запуск.
        """
        self.check_cancel()
        self.log(f"запуск {package}")
        control.launch_app(self.serial, package, activity, stop_first=stop_first)
        if wait:
            self.wait_app(package, timeout=wait)
            self.sleep(1.0)  # приложение на экране, дать дорисоваться

    def stop_app(self, package: str) -> None:
        control.stop_app(self.serial, package)

    def current_app(self) -> str:
        return control.current_app(self.serial)

    def wait_app(self, package: str, timeout: float = 20) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            self.check_cancel()
            if self.current_app() == package:
                return True
            time.sleep(0.5)
        return False

    def open_url(self, url: str) -> None:
        control.open_url(self.serial, url)

    def install(self, apk_path: str) -> str:
        self.log(f"установка {apk_path}")
        return control.install(self.serial, apk_path)

    def uninstall(self, package: str) -> str:
        return control.uninstall(self.serial, package)

    def grant(self, package: str, permission: str) -> None:
        control.grant(self.serial, package, permission)

    def packages(self, third_party_only: bool = True) -> list[str]:
        return adb.list_packages(self.serial, third_party_only)

    # ------------------------------------------------------------------ аккаунты
    def account(self, platform: str | None = None) -> dict:
        """Аккаунт, привязанный к этому телефону в разделе «Аккаунты».

        ``ctx.account("vk")["login"]`` вместо логина, зашитого в сценарий.
        """
        from . import accounts
        acc = accounts.for_device(self.serial, platform)
        if acc is None:
            where = f" для «{platform}»" if platform else ""
            raise StepFailed(f"к телефону не привязан аккаунт{where} — привяжите в разделе «Аккаунты»")
        return acc

    # ------------------------------------------------------------------ shell
    def shell(self, cmd: str | list[str], timeout: float = 30) -> str:
        self.check_cancel()
        return adb.shell(self.serial, cmd, timeout=timeout)

    # ------------------------------------------------------------------ артефакты
    def screenshot(self, name: str = "") -> str:
        """Сохранить скриншот в артефакты задачи, вернуть путь."""
        self._shot_n += 1
        base = self.artifacts_dir or config.ARTIFACTS_DIR
        base.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in (name or f"shot{self._shot_n}") if c.isalnum() or c in "-_")
        path = base / f"{self._shot_n:02d}_{safe}.jpg"
        control.save_screenshot(self.serial, path)
        self.log(f"скриншот → {path.name}")
        return str(path)

    def dump_hierarchy(self) -> str:
        return control.dump_hierarchy(self.serial)

    def save_hierarchy(self, name: str = "hierarchy") -> str:
        base = self.artifacts_dir or config.ARTIFACTS_DIR
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"{name}.xml"
        path.write_text(self.dump_hierarchy(), "utf-8")
        return str(path)

    def save_logcat(self, lines: int = 400, name: str = "logcat") -> str:
        base = self.artifacts_dir or config.ARTIFACTS_DIR
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"{name}.txt"
        path.write_text(control.logcat_tail(self.serial, lines), "utf-8")
        return str(path)

    # ------------------------------------------------------------------ устойчивость
    def watch_popups(self, *texts: str) -> None:
        """Автоматически закрывать всплывающие диалоги в фоне (u2 watchers)."""
        d = self.d
        if d is None:
            return
        defaults = ("ALLOW", "Allow", "Разрешить", "OK", "ОК", "Хорошо", "Принять", "While using the app")
        for t in (texts or defaults):
            try:
                d.watcher.when(t).click()
            except Exception:  # noqa: BLE001
                pass
        try:
            d.watcher.start()
        except Exception:  # noqa: BLE001
            pass

    def escape(self, ok: Callable[[], bool]) -> bool:
        """Выбраться с незнакомого экрана, не зная, что это за экран.

        Объявить каждую преграду заранее нельзя — их подсовывает чужое
        приложение. Но почти любая закрывается одним из четырёх действий,
        поэтому перебираем их, пока `ok()` не скажет, что мы выбрались.
        Перебор ограничен: страж с лимитом уже есть, а здесь потолок нужен,
        чтобы не тыкать «Назад» до конца таймаута и не выйти из приложения.
        """
        if not config.ESCAPE:
            return False
        # Слепок снимается ДО первого нажатия: после него на экране уже другое,
        # и опознавать преграду будет нечем. Пишем на диск только при удаче —
        # если выбраться не вышло, тот же экран снимет падение задачи, и два
        # слепка одного экрана только раздували бы карту отводов.
        слепок = self._obstacle_snapshot()
        for _ in range(ESCAPE_ROUNDS):
            for шаг in ESCAPE_STEPS:
                self.check_cancel()
                if шаг is None:
                    self.key("back")
                else:
                    self.click_if_exists(timeout=ESCAPE_PROBE, **шаг)
                if ok():
                    self.log("выбрались с незнакомого экрана")
                    self._report_escape(слепок)
                    return True
        return False

    def _obstacle_snapshot(self) -> dict:
        """Слепок текущего экрана: чем его опознать и что на нём написано."""
        try:
            return obstacle.capture(self.dump_hierarchy(), *self.size,
                                    package=self.current_app())
        except Exception as e:  # noqa: BLE001 — слепок не обязан получиться
            self.log(f"слепок незнакомого экрана не снялся: {e}")
            return {}

    def _report_escape(self, слепок: dict) -> None:
        """Записать преграду, которую обошли вслепую, и позвать человека.

        Иначе удачный выход ничего не оставляет после себя: прогон доехал, а
        экран, из-за которого пришлось тыкать «Назад», нигде не записан — и
        будет тыкаться вслепую на каждом прогоне. Ферма должна учиться на том,
        что сейчас проглатывает молча.
        """
        файл = self._save_obstacle(слепок) if слепок else ""
        тексты = ", ".join((слепок.get("texts") or [])[:3])
        кандидаты = слепок.get("candidates") or []
        try:
            dv.deviations.record(
                kind=dv.ESCAPE,
                title=f"незнакомый экран обошли вслепую: {тексты or слепок.get('package') or '?'}",
                detail="Сценарий доехал, но выход подобран перебором «назад / закрыть / "
                       "пропустить». Что это был за экран, ферма не знает — "
                       "покажите выход, и он станет отводом.",
                device_name=self.device_name,
                job_id=self.job_id,
                scenario_key=self.scenario_key,
                scenario_name=self.scenario_name,
                obstacle_file=файл,
                # Подпись — чем преграду опознали, а не тексты: на другом
                # устройстве тексты те же, а порядок в списке может разъехаться.
                signature=str(sorted(кандидаты[0]["selector"].items())) if кандидаты else "",
            )
        except Exception as e:  # noqa: BLE001 — запись не должна ронять прогон
            self.log(f"отклонение о незнакомом экране не записалось: {e}")

    def _save_obstacle(self, слепок: dict) -> str:
        """Слепок обойдённой преграды в артефакты задачи. Имя — с номером:
        за один прогон незнакомых экранов бывает несколько, а `obstacle.json`
        занят слепком падения."""
        if not self.artifacts_dir:
            return ""
        try:
            base = Path(self.artifacts_dir)
            base.mkdir(parents=True, exist_ok=True)
            self._escape_n += 1
            имя = f"obstacle_escaped_{self._escape_n:02d}.json"
            слепок = dict(слепок, escaped=True)
            (base / имя).write_text(
                json.dumps(слепок, ensure_ascii=False, indent=1), "utf-8")
            return имя
        except OSError as e:
            self.log(f"слепок обойдённой преграды не сохранился: {e}")
            return ""

    # ------------------------------------------------------------------ сторож
    def on_track(self, package: str, moved: bool = True) -> bool:
        """Сторож долгих циклов: мы ещё в своём приложении и экран живой?

        Листание ленты не промахивается никогда — поэтому без сторожа вылезшее
        окно («оцените приложение», «подозрительный вход») или выкинутое
        приложение ферма листала бы до конца сеанса. Зовут из цикла после
        каждого действия (`moved` — было ли листание с прошлого раза), а смотрит
        сторож не чаще WATCH_EVERY: дамп экрана на сорока телефонах не бесплатный.

        Сбились — сначала стражи и отводы (известные окна закрываются сами),
        потом вопрос человеку с кнопкой «показать, как быть». True — снова на
        своём экране; False — идём дальше как есть (человек велел не обращать
        внимания, или спросить некого).
        """
        if not config.WATCH:
            return True
        now = time.monotonic()
        if now - self._watch_at < config.WATCH_EVERY:
            return True
        self._watch_at = now
        беда = self._off_track(package, moved)
        if not беда:
            return True
        return self._lost(беда, lambda: not self._off_track(package, moved=False, again=True))

    def _off_track(self, package: str, moved: bool, again: bool = False) -> str:
        """Что не так с экраном, или "" — всё в порядке."""
        try:
            app = self.current_app()
        except Exception:  # noqa: BLE001 — не знаем, что впереди, — не повод тревожить
            return ""
        if package and app and app != package:
            return f"ушли из приложения: впереди {app}"
        # Много подписей, а не верхние: сверху в ленте — неподвижные вкладки и
        # меню, меняются подписи постов ниже.
        тексты = self._screen_texts(limit=60)
        подпись = "|".join(тексты)
        if again:
            # Пересверка после ответа человека: тот же экран, что был при
            # тревоге, — значит, ничего не поправили.
            return "экран не изменился" if подпись and подпись == self._watch_sig \
                and self._watch_same >= config.WATCH_SAME else ""
        # Пустой экран (видео, игра, веб) ничего не говорит: не считаем.
        if moved and подпись and подпись == self._watch_sig:
            self._watch_same += 1
        else:
            self._watch_same = 1 if подпись else 0
        self._watch_sig = подпись
        if self._watch_same >= config.WATCH_SAME:
            return f"экран не меняется, хотя листаю: [{', '.join(тексты[:4])}]"
        return ""

    def _lost(self, беда: str, fixed: Callable[[], bool]) -> bool:
        """Сбились с пути: стражи → вопрос человеку. True — снова на своём экране."""
        self.log(f"сбился: {беда}")
        if self._rescue() and fixed():
            self.log("окно закрыто стражем — продолжаю")
            self._watch_same = 0
            return True
        слепок = self._obstacle_snapshot()
        файл = self._save_lost(слепок) if слепок else ""
        if self._hold is None or not config.HOLD:
            # Спросить некого — ведём себя как раньше (идём дальше), но экран
            # не проглатываем молча: из отклонения его можно научить обходить.
            self._report_lost(беда, слепок, файл)
            self._watch_same = 0
            return False
        while True:
            решение = self._stuck(беда, kind="lost", obstacle=файл, refusal=HOLD_SKIP)
            if решение == HOLD_RETRY:
                if fixed():
                    self.log("снова на своём экране — продолжаю")
                    self._watch_same = 0
                    return True
                беда = f"всё ещё не тот экран: {беда}"
                continue
            if решение in (HOLD_SKIP, HOLD_GO):
                self._watch_same = 0
                return False
            self.fail(f"сбился с пути: {беда}")

    def _save_lost(self, слепок: dict) -> str:
        """Слепок экрана, на котором сбились: из него «показать, как быть»
        делает отвод. Номер в имени — за сеанс сбиться можно не раз."""
        if not self.artifacts_dir:
            return ""
        try:
            base = Path(self.artifacts_dir)
            base.mkdir(parents=True, exist_ok=True)
            self._lost_n += 1
            имя = f"obstacle_lost_{self._lost_n:02d}.json"
            (base / имя).write_text(
                json.dumps(dict(слепок, lost=True), ensure_ascii=False, indent=1), "utf-8")
            return имя
        except OSError as e:
            self.log(f"слепок экрана не сохранился: {e}")
            return ""

    def _report_lost(self, беда: str, слепок: dict, файл: str) -> None:
        тексты = ", ".join((слепок.get("texts") or [])[:3])
        кандидаты = слепок.get("candidates") or []
        try:
            dv.deviations.record(
                kind=dv.LOST,
                title=f"сбился с пути: {тексты or слепок.get('package') or беда}",
                detail=f"{беда}. Спросить было некого — сценарий пошёл дальше как есть. "
                       f"Покажите, как быть на этом экране, — дальше ферма справится сама.",
                device_name=self.device_name,
                job_id=self.job_id,
                scenario_key=self.scenario_key,
                scenario_name=self.scenario_name,
                obstacle_file=файл,
                signature=str(sorted(кандидаты[0]["selector"].items())) if кандидаты else беда,
            )
        except Exception as e:  # noqa: BLE001 — запись не должна ронять прогон
            self.log(f"отклонение «сбился» не записалось: {e}")

    # ------------------------------------------------------------------ блоки
    def run(self, key: str, **params) -> None:
        """Выполнить другой сценарий как блок.

        Пролог «разблокировать → запустить → войти» пишется один раз и
        вызывается отовсюду. Состояние прогона — человечный режим, стражи и
        их счётчики — общее: блок не начинает жизнь заново.
        """
        from . import scenarios  # внутри: scenarios импортирует context

        if key in self._stack:
            self.fail(f"блок «{key}» вызывает сам себя: {' → '.join(self._stack + [key])}")
        if len(self._stack) >= MAX_BLOCK_DEPTH:
            self.fail(f"вложенность блоков глубже {MAX_BLOCK_DEPTH}: "
                      f"{' → '.join(self._stack + [key])}")

        sc = scenarios.get(key)
        if sc is None:
            self.fail(f"блок «{key}» не найден в папке сценариев")
        if sc.error or sc.module is None:
            self.fail(f"блок «{key}» не загружается: "
                      f"{(sc.error or '').splitlines()[-1] if sc.error else 'нет модуля'}")

        self.log(f"→ блок «{key}»")
        снаружи = self.params
        self._stack.append(key)
        try:
            self.params = scenarios.resolve_params(sc, params)
            sc.module.run(self)
        except Cancelled:
            raise
        except StepFailed as e:
            # имя блока в сообщении: иначе «не найден элемент» непонятно чей
            raise StepFailed(f"блок «{key}»: {e}") from e
        finally:
            self._stack.pop()
            self.params = снаружи
        self.log(f"← блок «{key}» готов")

    def _rescue(self) -> bool:
        """Шаг промахнулся — дать стражам закрыть перехватчик. True, если был толк."""
        try:
            return bool(self._guards.try_all(self))
        except Cancelled:
            raise  # отмена пользователем — не сбой стражей, как в retry
        except Exception as e:  # noqa: BLE001 — стражи не должны ронять сценарий
            self.log(f"стражи упали: {e}")
            return False

    def attempt(self, fn: Callable[[], Any], retries: int = 0,
                optional: bool = False, what: str = "шаг", delay: float = 1.0):
        """Шаг с запасом прочности: `retries` повторов, затем пропуск или падение.

        Отличие от `retry`: у необязательного шага исчерпание попыток — не
        ошибка, а «пропущено», сценарий идёт дальше; отмена и ожидание человека
        (HELD) работают как обычно, потому что fn — обычный вызов ctx.
        """
        total = max(1, int(retries) + 1)
        last: Exception | None = None
        for i in range(1, total + 1):
            self.check_cancel()
            try:
                return fn()
            except Cancelled:
                raise
            except Exception as e:  # noqa: BLE001
                last = e
                if i < total:
                    self.log(f"{what}: попытка {i}/{total} не удалась ({e}), повторяю")
                    if self.step_mark:
                        self.step_mark("retried")
                    self.sleep(delay)
        if optional:
            self.log(f"{what}: необязательный шаг пропущен ({last})")
            try:
                self.screenshot("skipped")
            except Exception:  # noqa: BLE001 — кадр пропуска не должен ронять сценарий
                pass
            if self.step_mark:
                self.step_mark("skipped")
            return None
        raise last

    def retry(self, fn: Callable[[], Any], attempts: int = 3, delay: float = 1.0, what: str = "действие"):
        """Повторить нестабильное действие."""
        last = None
        for i in range(1, attempts + 1):
            self.check_cancel()
            try:
                return fn()
            except Cancelled:
                raise
            except Exception as e:  # noqa: BLE001
                last = e
                self.log(f"{what}: попытка {i}/{attempts} не удалась ({e})")
                time.sleep(delay)
        raise StepFailed(f"{what}: не удалось за {attempts} попыток — {last}")
