import asyncio
import logging

from utils.logger import get_logger, log_event

logger = get_logger(__name__)


class HeartbeatScheduler:
    """Trigger a heartbeat callback on the background asyncio loop."""

    def __init__(self, interval_seconds: float, fire_callback):
        self._interval = max(10.0, float(interval_seconds))
        self._fire_callback = fire_callback
        self._task: asyncio.Task | None = None
        self._enabled = False
        log_event(
            logger,
            logging.INFO,
            "heartbeat.initialized",
            interval_seconds=self._interval,
        )

    @property
    def interval_seconds(self) -> float:
        return self._interval

    @interval_seconds.setter
    def interval_seconds(self, value: float):
        self._interval = max(10.0, float(value))

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def _start_on_loop(self):
        if self._enabled:
            return
        self._enabled = True
        self._task = asyncio.create_task(self._loop())
        log_event(
            logger,
            logging.INFO,
            "heartbeat.scheduler_started",
            interval_seconds=self._interval,
        )

    def start(self, loop: asyncio.AbstractEventLoop):
        return asyncio.run_coroutine_threadsafe(self._start_on_loop(), loop)

    async def _stop_on_loop(self):
        self._enabled = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log_event(logger, logging.INFO, "heartbeat.scheduler_stopped")

    def stop(self, loop: asyncio.AbstractEventLoop):
        return asyncio.run_coroutine_threadsafe(self._stop_on_loop(), loop)

    async def _loop(self):
        try:
            while self._enabled:
                await asyncio.sleep(self._interval)
                if not self._enabled:
                    break
                try:
                    await self._fire_callback()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log_event(
                        logger,
                        logging.ERROR,
                        "heartbeat.fire_failed",
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
        except asyncio.CancelledError:
            pass
