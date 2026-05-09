import asyncio
import threading
import time

import pytest

from core.heartbeat import HeartbeatScheduler


@pytest.fixture
def loop_in_thread():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=1)
        loop.close()


def test_heartbeat_minimum_interval():
    scheduler = HeartbeatScheduler(interval_seconds=1, fire_callback=lambda: None)

    assert scheduler.interval_seconds == 10.0


def test_heartbeat_start_is_thread_safe(loop_in_thread):
    async def noop():
        return None

    scheduler = HeartbeatScheduler(interval_seconds=10, fire_callback=noop)
    scheduler._interval = 0.01

    scheduler.start(loop_in_thread).result(timeout=1)

    assert scheduler.is_enabled is True
    assert scheduler._task is not None

    scheduler.stop(loop_in_thread).result(timeout=1)


def test_heartbeat_fires_after_interval(loop_in_thread):
    fired = threading.Event()

    async def fire():
        fired.set()

    scheduler = HeartbeatScheduler(interval_seconds=10, fire_callback=fire)
    scheduler._interval = 0.01

    scheduler.start(loop_in_thread).result(timeout=1)

    assert fired.wait(timeout=1)

    scheduler.stop(loop_in_thread).result(timeout=1)


def test_heartbeat_stop_cancels_pending_tick(loop_in_thread):
    fired = threading.Event()

    async def fire():
        fired.set()

    scheduler = HeartbeatScheduler(interval_seconds=10, fire_callback=fire)
    scheduler._interval = 0.2

    scheduler.start(loop_in_thread).result(timeout=1)
    time.sleep(0.05)
    scheduler.stop(loop_in_thread).result(timeout=1)
    time.sleep(0.25)

    assert fired.is_set() is False


def test_heartbeat_callback_exception_does_not_crash_loop(loop_in_thread):
    attempts = []
    recovered = threading.Event()

    async def fire():
        attempts.append("tick")
        if len(attempts) == 1:
            raise RuntimeError("boom")
        recovered.set()

    scheduler = HeartbeatScheduler(interval_seconds=10, fire_callback=fire)
    scheduler._interval = 0.01

    scheduler.start(loop_in_thread).result(timeout=1)

    assert recovered.wait(timeout=1)
    assert len(attempts) >= 2

    scheduler.stop(loop_in_thread).result(timeout=1)


def test_heartbeat_stop_waits_for_cleanup(loop_in_thread):
    entered = threading.Event()
    cleaned = threading.Event()

    async def fire():
        entered.set()
        try:
            await asyncio.sleep(999)
        finally:
            cleaned.set()

    scheduler = HeartbeatScheduler(interval_seconds=10, fire_callback=fire)
    scheduler._interval = 0.01

    scheduler.start(loop_in_thread).result(timeout=1)

    assert entered.wait(timeout=1)
    scheduler.stop(loop_in_thread).result(timeout=1)

    assert cleaned.wait(timeout=1)

