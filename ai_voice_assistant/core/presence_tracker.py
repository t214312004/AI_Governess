import logging
import threading
import time

from utils.logger import get_logger, log_event

logger = get_logger(__name__)


class PresenceTracker:
    """Track likely nearby presence from recent voice or input activity."""

    def __init__(self, presence_ttl_seconds: float = 300.0, enabled: bool = True):
        self._lock = threading.Lock()
        self._enabled = bool(enabled)
        self._last_presence_time = 0.0
        self._ttl = max(0.0, float(presence_ttl_seconds))
        log_event(
            logger,
            logging.INFO,
            "presence_tracker.initialized",
            enabled=self._enabled,
            ttl_seconds=self._ttl,
        )

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def ttl_seconds(self) -> float:
        with self._lock:
            return self._ttl

    @ttl_seconds.setter
    def ttl_seconds(self, value: float):
        with self._lock:
            self._ttl = max(0.0, float(value))

    _LOG_RATE_LIMIT_SECONDS: float = 1.0

    def mark_present(self, source: str) -> None:
        with self._lock:
            if not self._enabled:
                return
            previous = self._last_presence_time
            current = time.monotonic()
            self._last_presence_time = current
            became_present = previous <= 0 or (current - previous) >= self._ttl
            elapsed_since_previous = -1.0 if previous <= 0 else (current - previous)
            should_log = (
                elapsed_since_previous < 0
                or elapsed_since_previous >= self._LOG_RATE_LIMIT_SECONDS
            )

        if should_log:
            log_event(
                logger,
                logging.DEBUG,
                "presence_tracker.marked",
                source=source,
                seconds_since_previous=elapsed_since_previous,
            )

        if became_present:
            log_event(
                logger,
                logging.INFO,
                "presence_tracker.became_present",
                source=source,
            )

    def is_present(self) -> bool:
        with self._lock:
            if not self._enabled or self._last_presence_time <= 0:
                return False
            return (time.monotonic() - self._last_presence_time) < self._ttl

    def seconds_since_last_presence(self) -> float:
        with self._lock:
            if not self._enabled or self._last_presence_time <= 0:
                return -1.0
            return time.monotonic() - self._last_presence_time

    def get_status_text(self) -> str:
        with self._lock:
            enabled = self._enabled
            last_presence_time = self._last_presence_time
            ttl = self._ttl

        if not enabled:
            return "在場偵測已停用，請視為附近可能無人"
        if last_presence_time <= 0:
            return "附近可能無人"

        elapsed = time.monotonic() - last_presence_time
        if elapsed < ttl:
            return "偵測到附近有人"

        minutes = int(elapsed // 60)
        if minutes < 1:
            return "附近可能無人，最近一分鐘內沒有偵測到活動"
        return f"附近可能無人，最近 {minutes} 分鐘沒有偵測到活動"
