"""Отклонения от сценария — то, что должен разобрать человек.

«Тревогами» назвать нельзя: этим словом на ферме уже зовут здоровье
устройств (перегрев, заряд), и два разных списка под одним именем путали бы.

Журнал задач отвечает на вопрос «что стало с этой задачей». Отклонения — на
другой: «где ферма пошла не по сценарию и что с этим делать». Поэтому они
живут отдельным списком, а не фильтром по журналу: одно и то же отклонение на
двадцати устройствах — это одна строка со счётчиком, потому что чинится оно
одним отводом, а не двадцатью.

Слияние идёт только с непрочитанными. Прочитанное означает «я это видел и
разобрался»; если то же самое случилось снова, это новость, а не прибавка к
счётчику старого.

Журнал в памяти, как у задач: отклонение без работающей фермы
смысла не имеет, а переживать перезапуск незачем — первый же прогон запишет
его заново.

Модуль не знает ни про adb, ни про FastAPI: на входе строки, на выходе
словари. Отсюда тестируемость без телефона.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

from . import config

log = logging.getLogger("farm.deviations")

# Виды отклонений. Список закрытый: отклонение, которое не умеет объяснить
# интерфейс, — это шум, а не сигнал.
FAIL = "fail"       # сценарий упал: дальше без человека никак
HOLD = "hold"       # задача стоит и ждёт решения, держа устройство и экран
ESCAPE = "escape"   # выбрались вслепую: сценарий доехал, но экран неизвестен
BRANCH = "branch"   # развилка не узнала экран: у сюжета появилась новая ветка
LAYER = "layer"     # цель нашлась не селектором: селектор устарел, но ещё жив
LOST = "lost"       # сторож долгого цикла: чужое приложение или застывший экран

KINDS = (FAIL, HOLD, ESCAPE, BRANCH, LAYER, LOST)

# Сколько устройств помнить в одном отклонении. Дальше важно только число: список
# из двадцати имён в строке всё равно не читается.
MAX_DEVICES = 8


@dataclass
class Deviation:
    id: str
    kind: str
    title: str
    detail: str = ""
    job_id: str = ""
    scenario_key: str = ""
    scenario_name: str = ""
    # Имя файла слепка преграды в артефактах задачи. Пусто — учить нечему:
    # кнопка «научить обходить» без слепка никуда не ведёт.
    obstacle_file: str = ""
    # Кадр экрана в момент отклонения (имя файла в артефактах задачи), что
    # искали (JSON {"sel": [...], "at": [x, y]}) и индекс шага в recipe.steps.
    # step_index -1 — шаг неизвестен (сценарий написан руками).
    shot: str = ""
    miss: str = ""
    step_index: int = -1
    at: float = field(default_factory=time.time)
    last_at: float = field(default_factory=time.time)
    hits: int = 1
    seen: bool = False
    devices: list = field(default_factory=list)
    signature: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "job_id": self.job_id,
            "scenario_key": self.scenario_key,
            "scenario_name": self.scenario_name,
            "obstacle_file": self.obstacle_file,
            "shot": self.shot,
            "miss": self.miss,
            "step_index": self.step_index,
            "at": self.at,
            "last_at": self.last_at,
            "hits": self.hits,
            "seen": self.seen,
            "devices": list(self.devices),
        }


class DeviationLog:
    """Журнал отклонений. Один на ферму, как runner."""

    def __init__(self) -> None:
        self._items: dict[str, Deviation] = {}
        self._order: deque = deque(maxlen=config.DEVIATION_HISTORY)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ запись
    def record(self, kind: str, title: str, detail: str = "",
               device_name: str = "", job_id: str = "",
               scenario_key: str = "", scenario_name: str = "",
               obstacle_file: str = "", signature: str = "",
               shot: str = "", miss: str = "",
               step_index: int = -1) -> Deviation:
        """Записать отклонение или прибавить к такому же непрочитанному.

        Ключ слияния — вид плюс `signature`. Подпись задаёт вызывающий, потому
        что «то же самое» для разных видов разное: для падения это текст
        ошибки, для слепой преграды — чем её опознали, для устаревшего
        селектора — сам селектор.
        """
        if kind not in KINDS:
            raise ValueError(f"неизвестный вид отклонения: {kind!r}")
        ключ = f"{kind}|{scenario_key}|{signature or title}"
        with self._lock:
            for item in self._живые():
                if item.seen or item.signature != ключ:
                    continue
                item.hits += 1
                item.last_at = time.time()
                if device_name and device_name not in item.devices:
                    if len(item.devices) < MAX_DEVICES:
                        item.devices.append(device_name)
                # Слепок берём у последней задачи: артефакты старых чистят, и
                # кнопка обучения на них со временем перестала бы работать.
                if obstacle_file:
                    item.obstacle_file = obstacle_file
                    item.job_id = job_id
                # По полям: побеждает последнее непустое значение каждого,
                # остальные остаются прежними. job_id едет за непустым shot
                # или obstacle_file — он указывает, в чьей папке лежит файл.
                # Кадр и промах берём так же — у последней задачи, но пустое
                # не затирает прежнее: лучше старый кадр, чем никакого.
                if shot:
                    item.shot = shot
                    item.job_id = job_id
                if miss:
                    item.miss = miss
                if step_index >= 0:
                    item.step_index = step_index
                return item

            item = Deviation(
                id=uuid.uuid4().hex[:12],
                kind=kind,
                title=title,
                detail=detail,
                job_id=job_id,
                scenario_key=scenario_key,
                scenario_name=scenario_name,
                obstacle_file=obstacle_file,
                shot=shot,
                miss=miss,
                step_index=step_index,
                devices=[device_name] if device_name else [],
                signature=ключ,
            )
            self._items[item.id] = item
            self._order.append(item.id)
            self._prune()
        log.warning("отклонение [%s] %s", kind, title)
        return item

    # ------------------------------------------------------------------ чтение
    def list(self, limit: int = 60, unseen_only: bool = False) -> list:
        with self._lock:
            out = []
            for item in self._живые(newest_first=True):
                if unseen_only and item.seen:
                    continue
                out.append(item.to_dict())
                if len(out) >= limit:
                    break
            return out

    def unseen(self) -> int:
        with self._lock:
            return sum(1 for a in self._живые() if not a.seen)

    # ------------------------------------------------------------------ правка
    def mark_seen(self, item_id: str | None = None) -> int:
        """Отметить прочитанным одно отклонение или все. Возвращает число задетых."""
        with self._lock:
            n = 0
            for item in self._живые():
                if item_id and item.id != item_id:
                    continue
                if not item.seen:
                    item.seen = True
                    n += 1
            return n

    def get(self, item_id: str) -> Deviation | None:
        with self._lock:
            return self._items.get(item_id)

    def resolve_hold(self, job_id: str) -> None:
        """Задача получила ответ человека — её строка «ждёт» в «Отклонениях»
        больше не о текущем, а об уже прошедшем: без этого она продолжала
        висеть непрочитанной с текстом «...без ответа задача упадёт через
        10 мин», хотя ответ давно дан (или задачу уже уронили) — то самое
        зависшее сообщение, которое не соответствует происходящему.
        """
        with self._lock:
            for item in self._items.values():
                if item.job_id == job_id and item.kind == HOLD and not item.seen:
                    item.seen = True

    def job_has_kind(self, job_id: str, kind: str) -> bool:
        """Есть ли у этой задачи отклонение данного вида.

        Нужно журналу задач: «PASSED» зелёным цветом означает лишь «сценарий
        не упал», а не «всё нашлось чисто» — резолвер мог доехать до цели
        запасным слоем (LAYER) или тапом вслепую, и об этом иначе узнают,
        только сверив id задачи со списком «Отклонения» руками.
        """
        if not job_id:
            return False
        with self._lock:
            return any(item.job_id == job_id and item.kind == kind
                       for item in self._items.values())

    def delete(self, item_id: str) -> bool:
        with self._lock:
            if self._items.pop(item_id, None) is None:
                return False
            try:
                self._order.remove(item_id)
            except ValueError:
                pass
            return True

    def clear(self) -> int:
        """Стереть журнал целиком: разобрались со всем, начинаем с чистого."""
        with self._lock:
            n = len(self._items)
            self._items.clear()
            self._order.clear()
            return n

    # ------------------------------------------------------------------ внутреннее
    def _живые(self, newest_first: bool = False) -> list:
        ids = list(self._order)
        if newest_first:
            ids.reverse()
        return [self._items[i] for i in ids if i in self._items]

    def _prune(self) -> None:
        """deque сам вытеснил самые старые id — снимаем с них и тела."""
        alive = set(self._order)
        for item_id in list(self._items):
            if item_id not in alive:
                self._items.pop(item_id, None)


deviations = DeviationLog()
