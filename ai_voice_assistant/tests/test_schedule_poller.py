import asyncio
import threading

import pytest

from core.schedule_poller import SchedulePoller


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


def test_schedule_poller_fires_immediately_and_stops(loop_in_thread):
    fired = threading.Event()

    async def fire():
        fired.set()

    poller = SchedulePoller(interval_seconds=0.25, fire_callback=fire)
    poller.start(loop_in_thread).result(timeout=1)

    assert fired.wait(timeout=1)
    assert poller.is_enabled is True

    poller.stop(loop_in_thread).result(timeout=1)
    assert poller.is_enabled is False


def test_schedule_poller_does_not_overlap_callbacks(loop_in_thread):
    entered = threading.Event()
    release = threading.Event()
    active_calls = 0
    max_active_calls = 0

    async def fire():
        nonlocal active_calls, max_active_calls
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        active_calls -= 1

    poller = SchedulePoller(interval_seconds=0.25, fire_callback=fire)
    poller.start(loop_in_thread).result(timeout=1)
    assert entered.wait(timeout=1)
    release.set()
    poller.stop(loop_in_thread).result(timeout=1)

    assert max_active_calls == 1
