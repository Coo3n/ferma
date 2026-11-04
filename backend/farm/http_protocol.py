"""Transport-level header deadline: slow headers never reach ASGI middleware."""
from __future__ import annotations

import h11
from uvicorn.protocols.http.h11_impl import H11Protocol


class BoundedH11Protocol(H11Protocol):
    HEADER_TIMEOUT = 15.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._header_timer = None

    def _cancel_header_timer(self):
        if self._header_timer is not None:
            self._header_timer.cancel()
            self._header_timer = None

    def _arm_header_timer(self):
        # More bytes must NOT extend the deadline (slowloris).
        if self._header_timer is None and not self.transport.is_closing():
            self._header_timer = self.loop.call_later(self.HEADER_TIMEOUT, self.transport.close)

    def connection_made(self, transport):
        super().connection_made(transport)
        self._arm_header_timer()

    def handle_events(self):
        super().handle_events()
        # h11 leaves IDLE only when a complete Request has been parsed.
        # Called for pipelined and keep-alive requests as well as the first one.
        if self.conn.their_state is h11.IDLE:
            self._arm_header_timer()
        else:
            self._cancel_header_timer()

    def connection_lost(self, exc):
        self._cancel_header_timer()
        super().connection_lost(exc)
