"""Защита телефона от разряда и перегрева.

ok → low (≤ BATTERY_LOW без зарядки: предупреждаем) → critical (≤ BATTERY_CRITICAL:
идёт таймер BATTERY_GRACE на реакцию) → rest (аварийно: ≤ BATTERY_STOP сразу,
критичный заряд без реакции, или перегрев ≥ TEMP_STOP_C). «Реакция» — кнопка
«Вижу» или подключённая зарядка. Из rest телефон выходит с гистерезисом:
заряд ≥ BATTERY_RESUME (на зарядке ≥ BATTERY_RESUME_CHARGING) и температура
< TEMP_RESUME_C. Модуль чистый: время и уровни приходят аргументами.
"""
from __future__ import annotations

import threading
import time

from .. import config

OK, LOW, CRITICAL, REST = "ok", "low", "critical", "rest"


class _State:
    def __init__(self) -> None:
        self.state = OK
        self.level: int | None = None
        self.grace_until = 0.0
        self.acked = False
        self.rest_reason = ""


class PowerGuard:
    def __init__(self) -> None:
        self._s: dict[str, _State] = {}
        self._lock = threading.Lock()

    def update(self, serial: str, level: int, temp: float | None, charging: bool,
               now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with self._lock:
            st = self._s.setdefault(serial, _State())
            was = st.state
            st.level = level
            hot = temp is not None and temp >= config.TEMP_STOP_C
            if was == REST:
                cool = temp is None or temp < config.TEMP_RESUME_C
                fed = level >= config.BATTERY_RESUME or (
                    charging and level >= config.BATTERY_RESUME_CHARGING)
                if fed and cool:
                    self._reset(st)
                    st.state = OK
            if st.state != REST:
                self._step(st, level, hot, temp, charging, now)
            return {"state": st.state, "rest_reason": st.rest_reason,
                    "entered_rest": st.state == REST and was != REST}

    def _step(self, st: _State, level: int, hot: bool, temp, charging: bool, now: float) -> None:
        if hot:
            return self._rest(st, f"перегрев {temp:.0f}°C")
        if charging:
            self._reset(st)
            return
        if level <= config.BATTERY_STOP:
            return self._rest(st, f"заряд {level}%")
        if level <= config.BATTERY_CRITICAL:
            if st.state != CRITICAL:
                st.state = CRITICAL
                st.grace_until = now + config.BATTERY_GRACE
            elif now >= st.grace_until and not st.acked:
                self._rest(st, f"заряд {level}%, никто не отреагировал")
            return
        st.state = LOW if level <= config.BATTERY_LOW else OK
        st.grace_until, st.acked = 0.0, False

    @staticmethod
    def _rest(st: _State, reason: str) -> None:
        st.state, st.rest_reason = REST, reason

    @staticmethod
    def _reset(st: _State) -> None:
        st.state, st.rest_reason, st.grace_until, st.acked = OK, "", 0.0, False

    def ack(self, serial: str) -> dict:
        with self._lock:
            st = self._s.setdefault(serial, _State())
            if st.state in (LOW, CRITICAL):
                st.acked = True
        return self.view(serial)

    def view(self, serial: str, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with self._lock:
            st = self._s.get(serial)
            if st is None:
                return {"level": None, "state": OK, "grace_left": None,
                        "acked": False, "rest_reason": "", "resume": config.BATTERY_RESUME}
            left = (max(0, int(st.grace_until - now))
                    if st.state == CRITICAL and not st.acked else None)
            return {"level": st.level, "state": st.state, "grace_left": left,
                    "acked": st.acked, "rest_reason": st.rest_reason,
                    "resume": config.BATTERY_RESUME}


guard = PowerGuard()
