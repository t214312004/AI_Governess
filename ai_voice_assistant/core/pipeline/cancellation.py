from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from time import monotonic
from typing import Callable


class CancelDisposition(str, Enum):
    PHYSICAL = "physical_cancelled"
    LOGICAL = "logically_suppressed"
    UNSUPPORTED = "unsupported"
    ALREADY_CANCELLED = "already_cancelled"


@dataclass(frozen=True, slots=True)
class CancelResult:
    disposition: CancelDisposition
    reason: str
    cancelled_at: float

    @property
    def prevents_stale_output(self) -> bool:
        return self.disposition in {
            CancelDisposition.PHYSICAL,
            CancelDisposition.LOGICAL,
            CancelDisposition.ALREADY_CANCELLED,
        }


class CancelScope:
    """Thread-safe cancellation state shared by all stages in one turn."""

    def __init__(self, response_generation: int):
        self.response_generation = int(response_generation)
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason = ""
        self._cancelled_at = 0.0
        self._callbacks: list[Callable[[str], bool | None]] = []

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def register(self, callback: Callable[[str], bool | None]) -> None:
        with self._lock:
            if self._event.is_set():
                reason = self._reason
            else:
                self._callbacks.append(callback)
                return
        callback(reason)

    def cancel(self, reason: str, *, physical_supported: bool = False) -> CancelResult:
        with self._lock:
            if self._event.is_set():
                return CancelResult(
                    CancelDisposition.ALREADY_CANCELLED,
                    self._reason,
                    self._cancelled_at,
                )
            self._reason = str(reason or "cancelled")
            self._cancelled_at = monotonic()
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
            self._event.set()

        physical_cancelled = False
        for callback in callbacks:
            try:
                physical_cancelled = bool(callback(self._reason)) or physical_cancelled
            except Exception:
                continue

        disposition = (
            CancelDisposition.PHYSICAL
            if physical_supported and physical_cancelled
            else CancelDisposition.LOGICAL
        )
        return CancelResult(disposition, self._reason, self._cancelled_at)

    def throw_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise RuntimeError(f"Turn cancelled: {self.reason}")
