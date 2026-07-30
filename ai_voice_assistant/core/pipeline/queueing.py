from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar


T = TypeVar("T")


class OverflowPolicy(str, Enum):
    REJECT = "reject"
    DROP_NEWEST = "drop_newest"
    DROP_OLDEST = "drop_oldest"
    COALESCE_LATEST = "coalesce_latest"


@dataclass(frozen=True, slots=True)
class QueueOfferResult:
    accepted: bool
    dropped: int = 0
    reason: str | None = None


class BoundedStageQueue(Generic[T]):
    def __init__(self, capacity: int, policy: OverflowPolicy = OverflowPolicy.REJECT):
        if int(capacity) <= 0:
            raise ValueError("capacity must be greater than zero")
        self.capacity = int(capacity)
        self.policy = policy
        self._queue: queue.Queue[T] = queue.Queue(maxsize=self.capacity)
        self._lock = threading.Lock()
        self.high_watermark = 0
        self.dropped_count = 0

    def offer(self, item: T) -> QueueOfferResult:
        with self._lock:
            dropped = 0
            if self._queue.full():
                if self.policy in {OverflowPolicy.REJECT, OverflowPolicy.DROP_NEWEST}:
                    self.dropped_count += 1
                    return QueueOfferResult(False, 1, self.policy.value)
                if self.policy == OverflowPolicy.COALESCE_LATEST:
                    while True:
                        try:
                            self._queue.get_nowait()
                            dropped += 1
                        except queue.Empty:
                            break
                else:
                    try:
                        self._queue.get_nowait()
                        dropped = 1
                    except queue.Empty:
                        pass
                self.dropped_count += dropped
            self._queue.put_nowait(item)
            self.high_watermark = max(self.high_watermark, self._queue.qsize())
            return QueueOfferResult(True, dropped)

    def get_nowait(self) -> T:
        return self._queue.get_nowait()

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    def drain(self) -> list[T]:
        result = []
        while True:
            try:
                result.append(self._queue.get_nowait())
            except queue.Empty:
                return result
