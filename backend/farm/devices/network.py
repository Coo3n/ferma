"""Сетевые устройства: `adb connect` и сторож, который держит их в строю.

Телефон на проводе adb находит сам. Плата в стойке подключена по Ethernet —
её адрес знает только ферма, и после каждого обрыва (ребут, потеря питания,
перезапуск adb-сервера) подключение надо восстанавливать руками. Этим и занят
сторож: раз в NETWORK_TICK секунд он сверяет список адресов с тем, что реально
видно в `adb devices`, и переподключает отставших.

Модуль намеренно ничего не знает о `registry`: состояние устройств ему
передают снаружи (`tick`). Так его можно проверять тестами без adb и без
живого реестра.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import adb, config

log = logging.getLogger("farm.network")

# Состояния цели. Не путать с состоянием устройства в реестре: здесь речь
# только о том, дошёл ли до платы adb connect.
UNKNOWN = "unknown"      # ещё не пробовали
PENDING = "pending"      # connect прошёл, ждём устройство в `adb devices`
CONNECTED = "connected"  # видно и работает
FAILED = "failed"        # не достучались, ждём следующей попытки
DISABLED = "disabled"    # выключено вручную


@dataclass
class Target:
    """Адрес платы и всё, что ферма о нём помнит."""

    address: str
    label: str = ""
    enabled: bool = True
    # ---- дальше только временное, в файл не попадает ----
    state: str = UNKNOWN
    error: str = ""
    attempts: int = 0    # неудач подряд, обнуляется успехом
    last_ok: float = 0.0
    last_try: float = 0.0
    next_try: float = 0.0

    def stored(self) -> dict:
        return {"address": self.address, "label": self.label, "enabled": self.enabled}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["online"] = self.state == CONNECTED
        d["retry_in"] = max(0.0, round(self.next_try - time.time(), 1))
        return d


def backoff(attempts: int) -> float:
    """Пауза перед следующей попыткой: 5, 10, 20, 40… до потолка."""
    if attempts <= 0:
        return 0.0
    delay = config.NETWORK_RETRY_BASE * (2 ** (attempts - 1))
    return min(delay, config.NETWORK_RETRY_MAX)


class NetworkDevices:
    """Список сетевых адресов, их состояние и фоновый сторож."""

    def __init__(self, path: Path | str | None = None, seed: str | None = None) -> None:
        self.path = Path(path if path is not None else config.NETWORK_FILE)
        self._targets: dict[str, Target] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._load()
        self._seed(config.NETWORK_SEED if seed is None else seed)

    # ---------- хранение ----------
    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except FileNotFoundError:
            return
        except Exception as e:  # noqa: BLE001 — битый файл не должен ронять ферму
            log.warning("не читается %s: %s", self.path, e)
            return
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                address = adb.normalize_target(item.get("address", ""), config.NETWORK_PORT)
            except ValueError as e:
                log.warning("пропущен адрес из файла: %s", e)
                continue
            t = Target(address=address, label=item.get("label", "") or "",
                       enabled=bool(item.get("enabled", True)))
            if not t.enabled:
                t.state = DISABLED
            self._targets[address] = t

    def _seed(self, seed: str) -> None:
        """Досыпать адреса из переменной окружения, не трогая уже известные."""
        for chunk in (seed or "").replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                address = adb.normalize_target(chunk, config.NETWORK_PORT)
            except ValueError as e:
                log.warning("FARM_NETWORK_DEVICES: %s", e)
                continue
            self._targets.setdefault(address, Target(address=address))

    def _save(self) -> None:
        with self._lock:
            data = [t.stored() for t in self._targets.values()]
        try:
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("не удалось сохранить %s: %s", self.path, e)

    # ---------- доступ ----------
    def all(self) -> list[Target]:
        with self._lock:
            return sorted(self._targets.values(), key=lambda t: t.address)

    def get(self, address: str) -> Target | None:
        with self._lock:
            return self._targets.get(address)

    def addresses(self) -> list[str]:
        with self._lock:
            return list(self._targets)

    def add(self, address: str, label: str = "") -> Target:
        """Добавить адрес. Повтор — не ошибка: обновит метку и вернёт цель."""
        address = adb.normalize_target(address, config.NETWORK_PORT)
        with self._lock:
            t = self._targets.get(address)
            if t is None:
                t = Target(address=address, label=label.strip())
                self._targets[address] = t
                log.info("новый сетевой адрес: %s", address)
            elif label.strip():
                t.label = label.strip()
            t.enabled = True
            t.attempts = 0
            t.next_try = 0.0
            if t.state == DISABLED:
                t.state = UNKNOWN
        self._save()
        return t

    def remove(self, address: str) -> bool:
        with self._lock:
            t = self._targets.pop(address, None)
        if t is None:
            return False
        adb.disconnect(address, timeout=config.NETWORK_CONNECT_TIMEOUT)
        self._save()
        log.info("сетевой адрес удалён: %s", address)
        return True

    def set_enabled(self, address: str, enabled: bool) -> Target | None:
        with self._lock:
            t = self._targets.get(address)
            if t is None:
                return None
            t.enabled = enabled
            t.attempts = 0
            t.next_try = 0.0
            t.state = UNKNOWN if enabled else DISABLED
            t.error = ""
        if not enabled:
            adb.disconnect(address, timeout=config.NETWORK_CONNECT_TIMEOUT)
        self._save()
        return t

    # ---------- подключение ----------
    def _mark_ok(self, t: Target, message: str, state: str) -> None:
        with self._lock:
            t.state = state
            t.error = ""
            t.attempts = 0
            t.next_try = 0.0
            if state == CONNECTED:
                t.last_ok = time.time()
        log.info("%s: %s", t.address, message)

    def _mark_fail(self, t: Target, message: str) -> None:
        with self._lock:
            t.attempts += 1
            t.state = FAILED
            t.error = message[:200]
            t.next_try = time.time() + backoff(t.attempts)
            attempts = t.attempts
        # Первые неудачи — обычное дело (плата грузится). Шумим только если
        # подключиться не удаётся упорно.
        (log.warning if attempts in (1, 3) or attempts % 10 == 0 else log.debug)(
            "%s: не подключиться (%d-я попытка): %s", t.address, attempts, message)

    def _try_connect(self, t: Target, stale: bool) -> bool:
        """Одна попытка. `stale` — адрес числится в adb, но не в строю."""
        t.last_try = time.time()
        if stale:
            # Мёртвую запись надо снять, иначе adb считает адрес занятым и
            # новый connect молча возвращает "already connected".
            adb.disconnect(t.address, timeout=config.NETWORK_CONNECT_TIMEOUT)
        ok, message = adb.connect(t.address, timeout=config.NETWORK_CONNECT_TIMEOUT)
        if ok:
            self._mark_ok(t, message, PENDING)
        else:
            self._mark_fail(t, message)
        return ok

    def connect_now(self, address: str) -> tuple[bool, str]:
        """Ручная попытка: сбрасывает паузу и переподключает с нуля."""
        t = self.get(address)
        if t is None:
            return False, "адрес не в списке"
        with self._lock:
            t.attempts = 0
            t.next_try = 0.0
        self._try_connect(t, stale=True)
        return t.state != FAILED, t.error or "подключение отправлено"

    # ---------- сторож ----------
    def tick(self, states: dict[str, str]) -> list[str]:
        """Один проход сторожа. `states` — серийник → состояние из `adb devices`.

        Возвращает адреса, к которым в этот проход стучались.
        """
        now = time.time()
        due: list[tuple[Target, bool]] = []

        with self._lock:
            targets = list(self._targets.values())

        for t in targets:
            if not t.enabled:
                t.state = DISABLED
                continue
            state = states.get(t.address)
            if state == "device":
                if t.state != CONNECTED:
                    self._mark_ok(t, "устройство в сети", CONNECTED)
                else:
                    t.last_ok = now
                continue
            if t.state == CONNECTED:
                # Только что было в строю — не ждём паузы, чиним сразу.
                t.state = PENDING
                t.next_try = 0.0
            if now < t.next_try:
                continue
            due.append((t, state is not None))

        if not due:
            return []

        workers = max(1, min(config.NETWORK_WORKERS, len(due)))
        if workers == 1:
            for t, stale in due:
                self._try_connect(t, stale)
        else:
            with ThreadPoolExecutor(max_workers=workers,
                                    thread_name_prefix="net-connect") as pool:
                list(pool.map(lambda item: self._try_connect(*item), due))
        return [t.address for t, _ in due]

    def settle(self, states: dict[str, str] | None = None) -> None:
        """Свериться с `adb devices`, но без попыток подключения.

        Нужно ответам API: после ручного connect устройство видно сразу, и
        ждать прохода сторожа, чтобы показать это в интерфейсе, незачем.
        """
        states = self.device_states() if states is None else states
        for t in self.all():
            if states.get(t.address) == "device" and t.state != CONNECTED:
                self._mark_ok(t, "устройство в сети", CONNECTED)

    def device_states(self) -> dict[str, str]:
        from .registry import registry  # поздний импорт: реестр знает про нас, мы про него — нет

        # Только то, что adb действительно показывал. Реестр заводит плитки и
        # для ни разу не виденных плат (last_seen == 0) — их нельзя принимать
        # за мёртвую запись в adb, иначе перед каждым connect летит лишний
        # disconnect.
        return {d.serial: d.state for d in registry.all() if d.last_seen}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        log.info("сторож сетевых устройств: адресов в списке — %d", len(self.addresses()))
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="network-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick(self.device_states())
            except Exception as e:  # noqa: BLE001
                log.exception("сбой сторожа: %s", e)
            self._stop.wait(config.NETWORK_TICK)


net = NetworkDevices()
