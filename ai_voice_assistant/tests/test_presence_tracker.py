import threading

from core import presence_tracker as presence_tracker_module
from core.presence_tracker import PresenceTracker


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def monotonic(self):
        return self.now


def test_initial_state_is_not_present():
    tracker = PresenceTracker()

    assert tracker.is_present() is False
    assert tracker.seconds_since_last_presence() == -1.0


def test_mark_present_makes_tracker_present(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(presence_tracker_module.time, "monotonic", clock.monotonic)
    tracker = PresenceTracker(presence_ttl_seconds=5)

    tracker.mark_present("audio")

    assert tracker.is_present() is True
    assert tracker.seconds_since_last_presence() == 0.0
    assert tracker.get_status_text() == "偵測到附近有人"


def test_presence_expires_after_ttl(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(presence_tracker_module.time, "monotonic", clock.monotonic)
    tracker = PresenceTracker(presence_ttl_seconds=5)

    tracker.mark_present("input")
    clock.now += 6

    assert tracker.is_present() is False
    assert tracker.get_status_text() == "附近可能無人，最近一分鐘內沒有偵測到活動"


def test_mark_present_resets_ttl(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(presence_tracker_module.time, "monotonic", clock.monotonic)
    tracker = PresenceTracker(presence_ttl_seconds=5)

    tracker.mark_present("audio")
    clock.now += 4
    tracker.mark_present("input")
    clock.now += 4

    assert tracker.is_present() is True


def test_get_status_text_reports_absence_in_minutes(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(presence_tracker_module.time, "monotonic", clock.monotonic)
    tracker = PresenceTracker(presence_ttl_seconds=5)

    tracker.mark_present("audio")
    clock.now += 130

    assert tracker.get_status_text() == "附近可能無人，最近 2 分鐘沒有偵測到活動"


def test_disabled_tracker_is_always_absent(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(presence_tracker_module.time, "monotonic", clock.monotonic)
    tracker = PresenceTracker(enabled=False)

    tracker.mark_present("audio")

    assert tracker.is_present() is False
    assert tracker.seconds_since_last_presence() == -1.0
    assert tracker.get_status_text() == "在場偵測已停用，請視為附近可能無人"


def test_thread_safety_under_concurrent_marks():
    tracker = PresenceTracker(presence_ttl_seconds=30)

    def worker():
        for _ in range(1000):
            tracker.mark_present("thread")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert tracker.is_present() is True

