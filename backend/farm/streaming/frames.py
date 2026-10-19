"""Трансляция экранов: один захватчик кадров на устройство, много зрителей.

Захват запускается только когда кто-то смотрит, и сам останавливается
через FARM_STREAM_IDLE_TIMEOUT секунд после ухода последнего зрителя.
Это то, что позволяет держать 20 устройств без нагрузки на хост.
"""
from __future__ import annotations

import logging
import threading
import time

from .. import adb, config, control
from ..devices import pool as u2pool

log = logging.getLogger("farm.screen")

BOUNDARY = "farmframe"


class FrameSource:
    def __init__(self, serial: str) -> None:
        self.serial = serial
        self.frame: bytes | None = None
        self.seq = 0
        self.generation = 0
        self.error: str = ""
        self.fps = config.STREAM_FPS
        self.max_width = config.STREAM_MAX_WIDTH
        self._cond = threading.Condition()
        self._last_request = 0.0
        self._viewers = 0
        self._live_viewers = 0      # зрители с ?live=1: человек управляет телефоном
        self._burst_until = 0.0     # после действия снимаем кадры без пауз
        self._wake = threading.Event()
        self.alive_at = time.time()  # последний удачный захват, даже если кадр не изменился
        self._thread: threading.Thread | None = None
        # RLock, а не Lock: add_viewer() держит его и вызывает _ensure_running(),
        # который берёт тот же замок. С обычным Lock это вечный дедлок.
        self._lock = threading.RLock()

    # ---- зрители ----
    def touch(self) -> None:
        self._last_request = time.time()
        self._ensure_running()

    def add_viewer(self, live: bool = False) -> None:
        with self._lock:
            self._viewers += 1
            if live:
                self._live_viewers += 1
            self._ensure_running()

    def remove_viewer(self, live: bool = False) -> None:
        with self._lock:
            self._viewers = max(0, self._viewers - 1)
            if live:
                self._live_viewers = max(0, self._live_viewers - 1)

    def note_action(self) -> None:
        """Человек только что тронул телефон: ответ должен быть виден сразу,
        а не через шаг обычной частоты кадров."""
        self._burst_until = time.time() + config.STREAM_BURST_SECONDS
        self._wake.set()

    def _interval(self) -> float:
        if time.time() < self._burst_until:
            return 0.0
        fps = config.STREAM_FPS_LIVE if self._live_viewers else self.fps
        return 1.0 / max(fps, 0.5)

    def new_generation(self) -> int:
        """Пометить всех текущих зрителей как устаревших и разбудить их.

        Браузер не всегда рвёт предыдущее MJPEG-соединение при смене src, а мы
        узнаём о разрыве только при неудачной записи — которой может не быть,
        пока клиент просто не читает сокет. Поэтому вытеснение делаем сами:
        новый зритель устройства закрывает поток предыдущего.
        """
        with self._cond:
            self.generation += 1
            self._cond.notify_all()
            return self.generation

    def _ensure_running(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, name=f"stream-{self.serial}", daemon=True)
            self._thread.start()

    def wait_frame(self, last_seq: int, timeout: float = 5.0) -> tuple[bytes | None, int]:
        with self._cond:
            if self.seq == last_seq:
                self._cond.wait(timeout)
            return self.frame, self.seq

    # ---- захват ----
    def _loop(self) -> None:
        log.info("старт трансляции %s", self.serial)
        while True:
            with self._lock:
                if self._viewers == 0 and time.time() - self._last_request >= config.STREAM_IDLE_TIMEOUT:
                    break
            t0 = time.time()
            screen_refresh(self.serial)
            try:
                width = config.STREAM_MAX_WIDTH_LIVE if self._live_viewers else self.max_width
                data = control.screenshot(self.serial, max_width=width, quality=config.STREAM_QUALITY)
                with self._cond:
                    self.alive_at = time.time()
                    self.error = ""
                    # Тот же кадр не шлём: экран стоит — трафик и перерисовка
                    # браузера не нужны. alive_at держит поток живым.
                    if data != self.frame:
                        self.frame = data
                        self.seq += 1
                    self._cond.notify_all()
            except Exception as e:  # noqa: BLE001
                self.error = str(e)[:200]
                with self._cond:
                    self._cond.notify_all()
                time.sleep(1.0)
            elapsed = time.time() - t0
            # Event вместо sleep: действие человека будит захват сразу.
            self._wake.wait(max(0.0, self._interval() - elapsed))
            self._wake.clear()
        log.info("стоп трансляции %s (нет зрителей)", self.serial)

    @property
    def last_request(self):
        return self._last_request


_sources: dict[str, FrameSource] = {}
_sources_lock = threading.Lock()


def source(serial: str) -> FrameSource:
    with _sources_lock:
        src = _sources.get(serial)
        if src is None:
            src = FrameSource(serial)
            _sources[serial] = src
        return src


def drop(serial: str) -> None:
    with _sources_lock:
        src = _sources.pop(serial, None)
    if src is not None:
        src.new_generation()  # осиротевший источник — закрыть его зрителей


def mjpeg(serial: str, live: bool = False):
    """Генератор multipart/x-mixed-replace для тега <img>.

    live — смотрит тот, кто управляет телефоном: кадры чаще и крупнее."""
    src = source(serial)
    gen = src.new_generation()
    src.add_viewer(live)
    src.touch()
    # Именно 0, а не -1: при seq == last_seq wait_frame() спит на условии,
    # а с -1 первый кадр ждался бы холостым циклом на полной загрузке CPU.
    last_seq = 0
    idle_since = time.time()
    try:
        while True:
            if src.generation != gen:
                log.info("вытеснен зритель %s (подключился новый)", serial)
                break
            src.touch()
            frame, seq = src.wait_frame(last_seq, timeout=5.0)
            if frame is None or seq == last_seq:
                if time.time() - max(idle_since, src.alive_at) > 30:
                    break  # устройство молчит полминуты — закрыть поток
                continue
            idle_since = time.time()
            last_seq = seq
            yield (
                    b"--" + BOUNDARY.encode() + b"\r\n"
                                                b"Content-Type: image/jpeg\r\n"
                                                b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                    + frame + b"\r\n"
            )
    finally:
        src.remove_viewer(live)
        log.info("отключен зритель %s (осталось %d)", serial, src._viewers)


# ---- горит ли экран ----
# Погасший или заблокированный телефон отдаёт старый/чёрный кадр, и плитка
# выглядела так, будто экран включён. Состояние узнаём в фоне (dumpsys —
# сотни мс, ждать его в горячем пути кадра нельзя) и не чаще SCREEN_TTL.
SCREEN_TTL = 4.0
_screen: dict[str, tuple[float, dict]] = {}
_screen_busy: set[str] = set()
_screen_guard = threading.Lock()


def _screen_check(serial: str, delay: float) -> None:
    try:
        time.sleep(delay)   # экрану нужно мгновение, чтобы погаснуть/загореться
        state = adb.screen_state(serial)
        if state is not None:
            _screen[serial] = (time.time(), state)
    finally:
        with _screen_guard:
            _screen_busy.discard(serial)


def screen_refresh(serial: str, force: bool = False) -> None:
    """Перепроверить экран в фоне, если сведения устарели (или force —
    после «разбудить/погасить/разблокировать», чтобы плашка сменилась сразу)."""
    hit = _screen.get(serial)
    if not force and hit and time.time() - hit[0] < SCREEN_TTL:
        return
    with _screen_guard:
        if serial in _screen_busy:
            return
        _screen_busy.add(serial)
    threading.Thread(target=_screen_check, args=(serial, 0.7 if force else 0.0), daemon=True,
                     name=f"screen-{serial}").start()


def screen_info(serial: str) -> dict | None:
    """Последнее известное состояние экрана или None, если ещё не знаем."""
    hit = _screen.get(serial)
    return hit[1] if hit else None


def note_action(serial: str) -> None:
    """Действие человека на телефоне → ускорить захват, если кто-то смотрит."""
    src = _sources.get(serial)
    if src is not None:
        src.note_action()


def is_live(serial: str, within: float = 8.0) -> bool:
    """Человек сейчас смотрит или управляет телефоном: фоновым опросам
    adb на нём лучше не мешать — каждый dumpsys делит канал с касаниями."""
    src = _sources.get(serial)
    return bool(src and (src._live_viewers or time.time() - src.last_request < within))


def snapshot(serial: str) -> bytes:
    """Одиночный кадр — берётся из уже идущей трансляции, если она есть."""
    src = _sources.get(serial)
    if src and src.frame and time.time() - src.last_request < 3:
        return src.frame
    return control.screenshot(serial, max_width=config.STREAM_MAX_WIDTH, quality=config.STREAM_QUALITY)


# ---- превью для плитки фермы ----

_thumbs: dict[str, tuple[float, bytes]] = {}
_thumb_locks: dict[str, threading.Lock] = {}
_thumb_guard = threading.Lock()


def _thumb_lock(serial: str) -> threading.Lock:
    with _thumb_guard:
        lock = _thumb_locks.get(serial)
        if lock is None:
            lock = _thumb_locks[serial] = threading.Lock()
        return lock


def _shrink(data: bytes) -> bytes:
    """Ужать готовый кадр трансляции до размера плитки."""
    import io

    from PIL import Image

    image = Image.open(io.BytesIO(data))
    if image.width <= config.THUMB_MAX_WIDTH:
        return data
    ratio = config.THUMB_MAX_WIDTH / image.width
    image = image.convert("RGB").resize(
        (config.THUMB_MAX_WIDTH, int(image.height * ratio)), Image.BILINEAR)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=config.THUMB_QUALITY)
    return buffer.getvalue()


def thumbnail(serial: str) -> bytes:
    """Мелкое превью с кэшем на THUMB_TTL секунд.

    Плитка фермы опрашивает все устройства разом, поэтому здесь важнее не
    свежесть, а чтобы N ячеек не превратились в N вызовов screencap. Замок
    на серийник схлопывает параллельные запросы в один захват, а кэш гасит
    повторы в пределах TTL. Идущая трансляция переиспользуется: её кадр уже
    снят, остаётся только ужать.
    """
    now = time.time()
    screen_refresh(serial)
    cached = _thumbs.get(serial)
    if cached and now - cached[0] < config.THUMB_TTL:
        return cached[1]
    # Экран погашен — снимать нечего: кадр был бы чёрным или старым.
    # Отдаём последний, плитка сама накроет его плашкой «экран выключен».
    state = screen_info(serial)
    if cached and state and not state["on"]:
        return cached[1]

    with _thumb_lock(serial):
        # Пока ждали замок, кадр мог снять сосед.
        cached = _thumbs.get(serial)
        if cached and time.time() - cached[0] < config.THUMB_TTL:
            return cached[1]

        src = _sources.get(serial)
        if src and src.frame and time.time() - src.last_request < 3:
            data = _shrink(src.frame)
        else:
            # Без быстрого соединения превью шло через adb screencap в
            # полноразмерный PNG — 1–3 с на кадр. Поднимаем его в фоне:
            # этот кадр ещё медленный, следующие — через uiautomator2.
            u2pool.warm_async(serial)
            data = control.screenshot(serial, max_width=config.THUMB_MAX_WIDTH,
                                      quality=config.THUMB_QUALITY)
        _thumbs[serial] = (time.time(), data)
        return data
