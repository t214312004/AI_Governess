import logging
import threading
import time
from enum import Enum, auto

from utils.logger import get_logger, log_event

logger = get_logger(__name__)


class State(Enum):
    IDLE_LISTEN = auto()
    COLLECTING = auto()
    SENDING = auto()
    SPEAKING = auto()
    HOT_LISTEN = auto()


class VoiceAssistantStateMachine:
    def __init__(self, hot_listen_timeout: float = 8.0):
        self._state = State.IDLE_LISTEN
        self._lock = threading.Lock()
        self.hot_listen_timeout = hot_listen_timeout
        self._hot_listen_start_time = 0.0

    @property
    def current_state(self) -> State:
        with self._lock:
            return self._state

    def transition(self, target_state: State):
        """Transition state in a thread-safe manner."""
        with self._lock:
            previous_state = self._state
            if previous_state == target_state:
                log_event(
                    logger,
                    logging.DEBUG,
                    "state.transition_ignored",
                    state=target_state.name,
                    reason="same_state",
                )
                return False
            log_event(
                logger,
                logging.INFO,
                "state.transition",
                from_state=previous_state.name,
                to_state=target_state.name,
            )
            self._state = target_state

            if target_state == State.HOT_LISTEN:
                self._hot_listen_start_time = time.monotonic()
            return True

    def get_hot_listen_elapsed(self) -> float:
        """Return elapsed seconds in `HOT_LISTEN`, or `0.0` otherwise."""
        with self._lock:
            if self._state != State.HOT_LISTEN:
                return 0.0
            return time.monotonic() - self._hot_listen_start_time

    def check_hot_listen_timeout(self) -> bool:
        """Check whether hot listen timed out without changing state."""
        with self._lock:
            return (
                self._state == State.HOT_LISTEN
                and time.monotonic() - self._hot_listen_start_time > self.hot_listen_timeout
            )

    def interrupt(self):
        """
        Force the current flow back to `COLLECTING`.
        """
        with self._lock:
            previous_state = self._state
            log_event(
                logger,
                logging.INFO,
                "state.interrupt",
                from_state=previous_state.name,
                to_state=State.COLLECTING.name,
            )
            if previous_state != State.COLLECTING:
                self._state = State.COLLECTING
            return previous_state
