"""Durable, process-safe daily quota. Only an attached visible host charges it."""
from datetime import datetime, timedelta, timezone, date
import json
import math
import os
from pathlib import Path
import tempfile
import time

TAIPEI = timezone(timedelta(hours=8))


def active_uptime():
    """Windows elapsed awake time excludes system sleep and hibernation."""
    if os.name != 'nt':
        return time.monotonic()
    import ctypes
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.QueryUnbiasedInterruptTime.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
    api.QueryUnbiasedInterruptTime.restype = ctypes.c_bool
    value = ctypes.c_ulonglong()
    if not api.QueryUnbiasedInterruptTime(ctypes.byref(value)):
        raise ctypes.WinError(ctypes.get_last_error())
    return value.value / 10_000_000


class HtmlUsageBudget:
    def __init__(self, state_dir, limit_seconds=1800, *, clock=active_uptime,
                 now=lambda: datetime.now(TAIPEI)):
        self.path = Path(state_dir) / 'html-usage.json'
        self.lock_path = self.path.with_suffix('.lock')
        self.limit = float(limit_seconds)
        if not math.isfinite(self.limit) or not 0 <= self.limit <= 86400:
            raise ValueError('HTML 額度無效')
        self.clock, self.now = clock, now
        self._stamp = clock()
        self._active = False
        self.used = 0.0
        self._update(0)

    @property
    def remaining(self):
        return max(0.0, self.limit - self.used)

    def refresh(self):
        self._update(0)
        return self.remaining

    def tick(self, active, *, settle=True):
        stamp = self.clock()
        delta = max(0.0, stamp - self._stamp) if self._active and (active or settle) else 0.0
        self._stamp = stamp
        self._active = bool(active)
        # A midnight crossing charges only elapsed time belonging to today.
        wall = self.now()
        midnight = wall.replace(hour=0, minute=0, second=0, microsecond=0)
        self._update(min(delta, max(0.0, (wall - midnight).total_seconds())))
        return self.remaining

    def _update(self, delta):
        from core.whiteboard_manager import _StateFileLock
        today = self.now().date().isoformat()
        with _StateFileLock(self.lock_path):
            if self.path.exists():
                record = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(record, dict) or type(record.get('version', 1)) is not int or record.get('version', 1) != 1:
                    raise ValueError('HTML 額度紀錄格式無效')
                day = record['day']
                if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
                    raise ValueError('HTML 額度紀錄日期無效')
                used = record['used_seconds']
                if type(used) not in (float, int) or not math.isfinite(used) or used < 0:
                    raise ValueError('HTML 額度紀錄損壞')
                if today > day:
                    used, day = 0.0, today
                # A backward wall clock retains the last recorded day and usage.
                # Awake time still consumes that allowance until the clock catches up.
            else:
                used, day = 0.0, today
            self.used = min(86400.0, used + delta)
            if not self.path.exists() or delta or day != record['day']:
                fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.html-usage-', suffix='.tmp')
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                        json.dump({'version': 1, 'day': day, 'used_seconds': self.used}, handle, allow_nan=False)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, self.path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
