import asyncio
import logging

from utils.logger import get_logger, log_event


logger = get_logger(__name__)


class SchedulePoller:
    """Small fixed-cadence poller used only to claim due schedules."""

    def __init__(self, interval_seconds: float, fire_callback):
        self._interval = max(0.25, float(interval_seconds))
        self._fire_callback = fire_callback
        self._enabled = False
        self._task = None

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def interval_seconds(self) -> float:
        return self._interval

    async def _start_on_loop(self):
        if self._enabled:
            return
        self._enabled = True
        self._task = asyncio.create_task(self._loop())
        log_event(
            logger,
            logging.INFO,
            "schedule.poller_started",
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
        log_event(logger, logging.INFO, "schedule.poller_stopped")

    def stop(self, loop: asyncio.AbstractEventLoop):
        return asyncio.run_coroutine_threadsafe(self._stop_on_loop(), loop)

    async def _loop(self):
        try:
            next_poll_at = asyncio.get_running_loop().time()
            while self._enabled:
                await asyncio.sleep(max(0.0, next_poll_at - asyncio.get_running_loop().time()))
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
                        "schedule.poll_failed",
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                now = asyncio.get_running_loop().time()
                next_poll_at += self._interval
                if next_poll_at <= now:
                    next_poll_at = now + self._interval
        except asyncio.CancelledError:
            pass
