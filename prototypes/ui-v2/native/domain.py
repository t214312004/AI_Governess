"""UI-independent session policies; shared by the real and demo adapters."""
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
import json
import math
import os
from pathlib import Path
import tempfile
import time

TAIPEI = timezone(timedelta(hours=8))


def finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False

@dataclass(frozen=True)
class SessionConfig:
    backend: str
    model: str
    effort: str
    voice_input: bool = True
    voice_output: bool = True
    html_minutes: int = 30
    chat_font: int = 21

    def __post_init__(self):
        if type(self.html_minutes) is not int or not 0 <= self.html_minutes <= 1440:
            raise ValueError('HTML 分鐘必須介於 0–1440')
        if any(not isinstance(value, str) for value in (self.backend, self.model, self.effort)):
            raise ValueError('Backend、Model、Effort 必須是文字')
        if not self.backend.strip() or not self.model.strip():
            raise ValueError('請先查詢模型')
        if type(self.voice_input) is not bool or type(self.voice_output) is not bool:
            raise ValueError('語音設定必須是布林值')
        if type(self.chat_font) is not int or self.chat_font not in (19, 21, 24):
            raise ValueError('不支援的對話字級')

class Phase(str, Enum):
    IDLE = 'idle'
    LISTENING = 'listening'
    THINKING = 'thinking'
    SPEAKING = 'speaking'

@dataclass(frozen=True)
class PendingMessage:
    id: int
    text: str

class SessionController:
    """Single owner of audio policy and FIFO. Cancellation invalidates old events."""
    def __init__(self, config: SessionConfig):
        self.config = config
        self.phase = Phase.IDLE
        self.manual_mute = not config.voice_input
        self.speaker_muted = not config.voice_output
        self.pending = deque()
        self.generation = 0
        self._next_id = 1

    @property
    def mic_muted(self):
        return not self.config.voice_input or self.manual_mute or self.phase == Phase.SPEAKING

    def enqueue(self, text):
        if not isinstance(text, str):
            raise ValueError('訊息必須是文字')
        text = text.strip()
        if not text:
            return False
        if len(text) > 8000 or len(self.pending) >= 10:
            raise ValueError('每則最多 8,000 字，最多排隊 10 則')
        self.pending.append(PendingMessage(self._next_id, text))
        self._next_id += 1
        return True

    def cancel_pending(self, message_id):
        self.pending = deque(item for item in self.pending if item.id != message_id)

    def take_next(self):
        if self.phase != Phase.IDLE or not self.pending:
            return None
        self.generation += 1
        self.phase = Phase.THINKING
        return self.pending.popleft(), self.generation

    def interrupt(self, listen=False):
        if listen and not self.config.voice_input:
            raise ValueError('固定文字輸入無法收音')
        self.generation += 1
        self.phase = Phase.LISTENING if listen else Phase.IDLE
        if listen:
            self.manual_mute = False

    def toggle_mic(self):
        if not self.config.voice_input:
            return 'locked'
        if self.phase == Phase.SPEAKING:
            self.interrupt(listen=True)
            return 'interrupt'
        self.manual_mute = not self.manual_mute
        if self.manual_mute and self.phase == Phase.LISTENING:
            self.interrupt()
        return 'changed'

    def toggle_speaker(self):
        if not self.config.voice_output:
            return 'locked'
        self.speaker_muted = not self.speaker_muted
        return 'changed'

    def finish(self, generation):
        if generation != self.generation or self.phase not in (Phase.THINKING, Phase.SPEAKING):
            return False
        self.phase = Phase.IDLE
        return True

class HtmlBudget:
    """Atomic, restart-persistent per-day usage. Time source injectable for tests.

    The demo enforces one process per runtime directory. Machine-wide permissions
    and a shared transactional store are separate integration work.
    """
    def __init__(self, path: Path, limit_seconds: float, wall=None, mono=None):
        if not finite_number(limit_seconds) or not 0 <= limit_seconds <= 86400:
            raise ValueError('額度上限無效')
        self.path = Path(path)
        self.limit = limit_seconds
        self.wall = wall or (lambda: datetime.now(TAIPEI))
        self.mono = mono or time.monotonic
        self.day = self.wall().date().isoformat()
        self.used = 0.0
        if self.path.exists():
            if self.path.stat().st_size > 4096:
                raise ValueError('額度記錄過大')
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or set(data) != {'day', 'used'}:
                raise ValueError('額度記錄格式無效')
            try:
                saved_day = date.fromisoformat(data['day']).isoformat()
            except (TypeError, ValueError):
                raise ValueError('額度日期無效') from None
            used = data['used']
            if not finite_number(used) or used < 0:
                raise ValueError('額度記錄無效，請檢查 demo runtime')
            if saved_day != data['day']:
                raise ValueError('額度日期必須使用 YYYY-MM-DD')
            if saved_day >= self.day:
                self.day = saved_day
                self.used = float(used)
        self._last_mono = self.mono()
        self._last_wall = self.wall()
        self._saved = None

    @property
    def remaining(self):
        return max(0.0, self.limit - self.used)

    def tick(self, charge: bool):
        now, stamp = self.wall(), self.mono()
        elapsed = max(0, stamp - self._last_mono)
        new_day = now.date().isoformat()
        if new_day > self.day:
            # Only charge the post-midnight part to the new day.
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            self.used = min(elapsed, max(0, (now-midnight).total_seconds())) if charge else 0.0
            self.day = new_day
        elif charge:
            self.used += elapsed
        self._last_mono, self._last_wall = stamp, now
        return self.remaining

    def save(self):
        state = (self.day, self.used)
        if self._saved == state:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A failed replacement leaves the previous valid record intact.
        fd, temp = tempfile.mkstemp(dir=self.path.parent, prefix='.quota-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
                json.dump({'day': self.day, 'used': self.used}, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
            self._saved = state
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
