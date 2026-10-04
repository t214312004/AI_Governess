"""Replace these adapters with CLI/audio implementations after UI approval."""
from dataclasses import dataclass
import threading
from typing import Callable, Protocol

@dataclass(frozen=True)
class ModelInfo:
    id: str
    efforts: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip() or len(self.id) > 200:
            raise ValueError('模型識別字無效')
        if not isinstance(self.efforts, tuple) or any(not isinstance(e, str) or not e.strip() for e in self.efforts) or len(set(self.efforts)) != len(self.efforts):
            raise ValueError('Effort 清單無效')

class Catalog(Protocol):
    # Real adapters must bound subprocess/network waits and honor cancellation.
    def query(self, backend: str, update: bool, *, cancel: threading.Event, timeout: float) -> tuple[ModelInfo, ...]: ...

class DemoCatalog:
    def query(self, backend, update, *, cancel, timeout):
        # Fictional results, deliberately not a production model catalog.
        return (ModelInfo('demo-balanced', ('low', 'medium', 'high')),
                ModelInfo('demo-fast', ()))

class TurnService(Protocol):
    """Events may arrive on any thread; cancelled generations must emit nothing.

    text is a complete message. Exactly one generation_done and playback_done
    terminate success; error terminates failure. Streaming needs a distinct API.
    """
    def start(self, text: str, event: Callable[[str, str], None]) -> None: ...
    def cancel(self) -> None: ...
    def mute_output(self) -> None: ...

class DemoTurnService:
    """Uses Tk scheduler; the controller sees the same events as a real adapter.

    generation_done and playback_done are distinct. Muting never cancels text.
    """
    def __init__(self, scheduler, can_speak):
        self.scheduler = scheduler
        self.can_speak = can_speak
        self.jobs = []
        self.playback_job = None
        self.event = None
        self.token = 0

    def _later(self, ms, callback):
        token = self.token
        def run():
            if job in self.jobs:
                self.jobs.remove(job)
            if token == self.token:
                callback()
        job = self.scheduler.after(ms, run)
        self.jobs.append(job)
        return job

    def start(self, text, event):
        self.cancel()
        self.event = event
        token = self.token
        response = f'已收到：{text}\n\n這是模擬回覆。'
        def generated():
            def emit(kind, payload=''):
                if token != self.token:
                    return False
                event(kind, payload)
                return token == self.token
            if not emit('text', response) or not emit('generation_done'):
                return
            if self.can_speak():
                if emit('playback_started'):
                    self.playback_job = self._later(12000, lambda: self._playback_done(token))
            else:
                emit('playback_done')
        self._later(900, generated)

    def _playback_done(self, token):
        if token != self.token:
            return
        self.playback_job = None
        if self.event:
            self.event('playback_done', '')

    def mute_output(self):
        if self.playback_job:
            self.scheduler.after_cancel(self.playback_job)
            self.jobs.remove(self.playback_job)
            self._playback_done(self.token)

    def cancel(self):
        self.token += 1
        for job in self.jobs:
            try:
                self.scheduler.after_cancel(job)
            except Exception:
                pass
        self.jobs.clear()
        self.playback_job = None
        self.event = None
