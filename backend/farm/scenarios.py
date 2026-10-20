"""Загрузка сценариев из папки scenarios/ с горячей перезагрузкой.

Сценарий — обычный python-файл с функцией `run(ctx)`. Опционально:
    NAME = "Человекочитаемое имя"
    DESCRIPTION = "Что делает"
    PARAMS = {"package": {"label": "Пакет", "default": "com.android.settings"}}
    TEMPLATE = True   # готовый шаблон: группа «Готовые шаблоны» в интерфейсе
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import logging
import sys
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import accounts, config
from .devices import registry

log = logging.getLogger("farm.scenarios")

# Маркер файлов, собранных конструктором. Ищется и в тексте: у сломанного файла
# модуль не импортируется, а удалять его из интерфейса всё равно нужно.
RECORDED_MARK = "RECORDED = True"
MARK_SCAN_CHARS = 400


@dataclass
class Scenario:
    key: str
    name: str
    description: str
    params: dict
    path: str
    mtime: float
    error: str = ""
    recorded: bool = False
    module: object | None = field(default=None, repr=False)
    # sha256 ровно тех байт, что скомпилированы в module: runner сверяет с ним
    # code_sha256 рецепта, чтобы не приписать падению шаг от другой версии кода.
    # Пусто, если файл не прочитан.
    sha256: str = ""
    # Платформы из ctx.account("vk") в коде: проверка перед запуском видит,
    # каким телефонам не хватит аккаунта, до того как сценарий упадёт.
    needs_accounts: list = field(default_factory=list)
    # TEMPLATE = True в модуле: готовый шаблон фермы (прогрев и т.п.) —
    # интерфейс показывает такие отдельной группой сверху списка.
    template: bool = False
    # COMMAND = True: короткая команда (до COMMAND_MAX_STEPS шагов), не сценарий.
    command: bool = False

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "params": self.params,
            "path": self.path,
            "error": self.error,
            "recorded": self.recorded,
            "needs_accounts": self.needs_accounts,
            "template": self.template,
            "command": self.command,
        }


_cache: dict[str, Scenario] = {}
# Штамп файла на момент загрузки: (st_mtime_ns, st_size). Float-mtime терял
# перезапись в тот же тик грубой файловой системы. Same-size + same-mtime_ns
# так не поймать, а хешировать файлы на каждый опрос дорого — этот случай
# закрывает явный invalidate(key) (его зовёт recorder.save после записи .py).
_stamps: dict[str, tuple[int, int]] = {}


# discover и invalidate идут из разных потоков (опрос API, recorder.save):
# без замка опрос, начавший чтение до invalidate, вернул бы старый модуль в кэш
# уже ПОСЛЕ сброса. RLock: get() -> discover() не должен блокировать сам себя.
# Верхний уровень кода сценария исполняется ПОД этим замком: не блокироваться.
_lock = threading.RLock()

# Ключи файлов, о которых уже предупредили (нечитаемый файл, петля симлинка):
# опрос идёт постоянно, и одно и то же предупреждение не должно сыпаться в лог.
_warned: set[str] = set()


def _warn_unreadable(key: str, path: Path, exc: OSError) -> None:
    if key not in _warned:
        _warned.add(key)
        log.warning("сценарий %s пропущен, файл не читается (%s): %s", key, path, exc)


def _stamp(path: Path) -> tuple[int, int]:
    st = path.stat()
    return st.st_mtime_ns, st.st_size


def invalidate(key: str) -> None:
    """Выкинуть сценарий из кэша: следующий discover/get загрузит файл заново."""
    with _lock:
        _cache.pop(key, None)
        _stamps.pop(key, None)


def is_recorded(path: Path) -> bool:
    """Записан ли файл конструктором (публичная обёртка над _marked)."""
    return _marked(path)


def _marked(path: Path) -> bool:
    try:
        # errors="replace": файл в чужой кодировке не должен ронять сканирование
        text = path.read_bytes()[:MARK_SCAN_CHARS * 4].decode("utf-8", "replace")
        return RECORDED_MARK in text[:MARK_SCAN_CHARS]
    except (OSError, ValueError):
        return False


def _load_file(path: Path) -> Scenario:
    key = path.stem
    mtime = path.stat().st_mtime
    mod_name = f"farm_scenario_{key}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        return Scenario(key, key, "", {}, str(path), mtime,
                        error="не удалось прочитать файл", recorded=_marked(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        # исходник читаем сами, мимо __pycache__: pyc валидируется по mtime+size
        # и при перезаписи в тот же тик отдал бы старый байткод.
        # Компилятору отдаём БАЙТЫ: он сам учтёт BOM и PEP 263 (coding: cp1251),
        # как это делал exec_module; read_text("utf-8") их ломает.
        # dont_inherit: иначе `from __future__ import annotations` этого модуля
        # протёк бы в сценарии (аннотации стали бы строками).
        # filename == str(path): по нему runner сопоставляет кадры traceback.
        source = path.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        code = compile(source, str(path), "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except SystemExit as e:  # sys.exit() в теле сценария не должен ронять сканирование
        return Scenario(key, key, "", {}, str(path), mtime,
                        error=f"сценарий вызвал выход из программы при загрузке (код {e.code})",
                        recorded=_marked(path))
    except Exception:  # noqa: BLE001  (в т.ч. SyntaxError/ValueError декодирования)
        return Scenario(key, key, "", {}, str(path), mtime,
                        error=traceback.format_exc(limit=3), recorded=_marked(path))

    if not callable(getattr(module, "run", None)):
        return Scenario(key, key, "", {}, str(path), mtime,
                        error="нет функции run(ctx)",
                        recorded=bool(getattr(module, "RECORDED", False)))

    return Scenario(
        key=key,
        name=getattr(module, "NAME", key),
        description=getattr(module, "DESCRIPTION", (module.__doc__ or "").strip()),
        params=getattr(module, "PARAMS", {}) or {},
        path=str(path),
        mtime=mtime,
        recorded=bool(getattr(module, "RECORDED", False)),
        module=module,
        sha256=digest,
        needs_accounts=needs_accounts(source),
        template=bool(getattr(module, "TEMPLATE", False)),
        command=bool(getattr(module, "COMMAND", False)),
    )


def needs_accounts(source: str | bytes) -> list[str]:
    """Платформы, которые сценарий берёт через ctx.account("<p>").

    Только строковые литералы из accounts.PLATFORMS: ctx.account(переменная)
    не угадываем — такой сценарий просто останется без проверки, а не
    получит ложную тревогу.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "account" and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in accounts.PLATFORMS):
            found.add(node.args[0].value)
    return sorted(found)


PREFLIGHT_STATUSES = ("ready", "offline", "busy", "no_account", "banned", "login")


def preflight(sc, serials: list[str]) -> dict:
    """Готов ли каждый телефон к запуску сценария — до запуска, а не по падениям.

    busy — не отказ: задача встанет в очередь телефона. login — запускаем, но
    предупреждаем: аккаунт помечен «нужен вход».
    """
    devices, counts = {}, {}
    for serial in dict.fromkeys(serials):
        dev = registry.get(serial)
        info = {"status": "ready"}
        if dev is None or not dev.online:
            info["status"] = "offline"
        elif dev.busy_job:
            info["status"] = "busy"
        else:
            for platform in sc.needs_accounts or []:
                acc = accounts.for_device(serial, platform)
                if acc is None:
                    info = {"status": "no_account", "platform": platform}
                elif acc.get("status") == "banned":
                    info = {"status": "banned", "platform": platform}
                elif acc.get("status") == "login" and info["status"] == "ready":
                    info = {"status": "login", "platform": platform}
                if info["status"] in ("no_account", "banned"):
                    break
        devices[serial] = info
        counts[info["status"]] = counts.get(info["status"], 0) + 1
    return {"counts": counts, "devices": devices}


def discover(force: bool = False) -> list[Scenario]:
    """Просканировать папку. Изменённые файлы перезагружаются автоматически."""
    with _lock:
        found: dict[str, Scenario] = {}
        stamps: dict[str, tuple[int, int]] = {}
        for path in sorted(Path(config.SCENARIOS_DIR).glob("*.py")):
            if path.name.startswith("_"):
                continue
            key = path.stem
            cached = _cache.get(key)
            try:
                stamp = _stamp(path)
                if cached and not force and _stamps.get(key) == stamp and not cached.error:
                    found[key] = cached
                    stamps[key] = stamp
                    _warned.discard(key)
                    continue
                # файл мог исчезнуть между штампом и загрузкой
                found[key] = _load_file(path)
                stamps[key] = stamp
                _warned.discard(key)
            except OSError as e:
                _warn_unreadable(key, path, e)
                continue
            if found[key].error:
                log.warning("сценарий %s: %s", key, found[key].error.splitlines()[-1])
        _cache.clear()
        _cache.update(found)
        _stamps.clear()
        _stamps.update(stamps)
        return sorted(found.values(), key=lambda s: s.name.lower())


def get(key: str) -> Scenario | None:
    discover()
    return _cache.get(key)


def resolve_params(scenario: Scenario, given: dict | None) -> dict:
    """Подставить значения по умолчанию и проверить обязательные параметры."""
    given = dict(given or {})
    result = {}
    for name, spec in (scenario.params or {}).items():
        spec = spec if isinstance(spec, dict) else {"default": spec}
        if name in given and given[name] not in (None, ""):
            result[name] = given.pop(name)
        elif "default" in spec:
            result[name] = spec["default"]
        elif spec.get("required"):
            raise ValueError(f"не задан обязательный параметр «{spec.get('label', name)}»")
        else:
            result[name] = None
    result.update(given)  # разрешаем произвольные доп. параметры
    return result
