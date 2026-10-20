"""Стражи — известные перехватчики: «если на экране X, нажми Y и продолжай».

Файлы guards/global.json (всегда) и guards/<package>.json (когда пакет на
экране), горячая перезагрузка по mtime, как у сценариев. Битый файл или битый
страж пропускаются с предупреждением: ферму они не роняют.

Модуль не знает про adb — экран он видит через утиный ctx
(exists/click_if_exists/key/current_app/log), поэтому тестируется на фейке.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from . import config

log = logging.getLogger("farm.guards")

DEFAULT_MAX_FIRES = 3   # потолок срабатываний одного стража за прогон
PROBE_TIMEOUT = 0.5     # сек на проверку одного признака when
ACTION_TIMEOUT = 1.5    # сек на поиск цели действия


@dataclass
class Guard:
    name: str
    when: list          # u2-селекторы; страж срабатывает по любому из них
    action: dict        # {"click": селектор} | {"key": имя клавиши}
    max_fires: int
    source: str


class GuardError(ValueError):
    """Страж не проходит проверку — пропускается с предупреждением."""


def _parse_guard(raw, source: str) -> Guard:
    if not isinstance(raw, dict):
        raise GuardError(f"{source}: страж должен быть объектом")
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise GuardError(f"{source}: у стража нет имени")
    when = (raw.get("when") or {}).get("any")
    if (not isinstance(when, list) or not when
            or not all(isinstance(s, dict) and s for s in when)):
        raise GuardError(f"{source}/{name}: when.any — непустой список селекторов")
    action = raw.get("action")
    if (not isinstance(action, dict) or len(action) != 1
            or next(iter(action)) not in ("click", "key", "run")):
        raise GuardError(f"{source}/{name}: action — ровно одно из click|key|run")
    if "run" in action and not (isinstance(action["run"], str) and action["run"].strip()):
        raise GuardError(f"{source}/{name}: action.run — ключ сценария")
    if "click" in action and not (isinstance(action["click"], dict) and action["click"]):
        raise GuardError(f"{source}/{name}: action.click — непустой селектор")
    if "key" in action and not (isinstance(action["key"], str) and action["key"]):
        raise GuardError(f"{source}/{name}: action.key — имя клавиши")
    max_fires = raw.get("max_fires", DEFAULT_MAX_FIRES)
    if not isinstance(max_fires, int) or isinstance(max_fires, bool) or max_fires < 1:
        raise GuardError(f"{source}/{name}: max_fires — целое ≥ 1")
    return Guard(name=name, when=when, action=action,
                 max_fires=max_fires, source=source)


_cache: dict[str, tuple[float, list]] = {}


def _load_file(path: Path) -> list:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    cached = _cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    out = []
    try:
        raw = json.loads(path.read_text("utf-8"))
        if not isinstance(raw, list):
            raise GuardError(f"{path.name}: ожидается список стражей")
        for item in raw:
            try:
                out.append(_parse_guard(item, path.stem))
            except GuardError as e:
                log.warning("страж пропущен: %s", e)
    except (OSError, json.JSONDecodeError, GuardError) as e:
        log.warning("файл стражей %s не читается: %s", path.name, e)
        out = []
    _cache[str(path)] = (mtime, out)
    return out


def load(package: str = "") -> list:
    """global.json плюс <package>.json, если пакет задан."""
    root = Path(config.GUARDS_DIR)
    found = list(_load_file(root / "global.json"))
    if package:
        found += _load_file(root / f"{package}.json")
    return found


# Сценарии, где правила окон выключены человеком («этому сценарию не
# помогать»): список ключей рядом с файлами стражей.
OFF_FILE = "scenarios_off.json"


def _off_path() -> Path:
    return Path(config.GUARDS_DIR) / OFF_FILE


def scenarios_off() -> set:
    try:
        data = json.loads(_off_path().read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {k for k in data if isinstance(k, str)} if isinstance(data, list) else set()


def set_scenario_off(key: str, off: bool) -> None:
    keys = scenarios_off()
    if off:
        keys.add(key)
    else:
        keys.discard(key)
    path = _off_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(keys), ensure_ascii=False), "utf-8")


class GuardEngine:
    """Счётчики срабатываний. Живёт один прогон задачи — внутри ctx."""

    def __init__(self) -> None:
        self._fired: dict[str, int] = {}

    def try_all(self, ctx) -> list[str]:
        try:
            package = ctx.current_app()
        except Exception:  # noqa: BLE001 — без пакета работают глобальные
            package = ""
        fired = []
        for guard in load(package):
            if self._fired.get(guard.name, 0) >= guard.max_fires:
                continue
            if not any(ctx.exists(timeout=PROBE_TIMEOUT, **sel) for sel in guard.when):
                continue
            # Счётчик — это попытка (when совпал), а не успех: страж с битым
            # action иначе не исчерпает max_fires никогда и будет проверяться
            # на каждом _rescue() — 2 с впустую на каждом промахе шага.
            self._fired[guard.name] = self._fired.get(guard.name, 0) + 1
            if self._apply(ctx, guard):
                fired.append(guard.name)
                ctx.log(f"страж «{guard.name}» сработал")
        return fired

    @staticmethod
    def _apply(ctx, guard) -> bool:
        if "click" in guard.action:
            return bool(ctx.click_if_exists(timeout=ACTION_TIMEOUT,
                                            **guard.action["click"]))
        if "run" in guard.action:
            # Отвод — обычный сценарий. Упал внутри — преграда не обойдена, но
            # разбор остальных стражей продолжается: одна кривая ветка не
            # должна лишать сценарий других попыток.
            try:
                ctx.run(guard.action["run"])
                return True
            except Exception as e:  # noqa: BLE001
                from .context import Cancelled  # поздний импорт: context знает про guards
                if isinstance(e, Cancelled):
                    raise      # отмена пользователем — не «отвод не сработал»
                ctx.log(f"отвод «{guard.action['run']}» не сработал: {e}")
                return False
        ctx.key(guard.action["key"])
        return True
