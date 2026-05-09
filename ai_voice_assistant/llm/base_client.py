from abc import ABC, abstractmethod
from typing import AsyncGenerator


STREAM_ACTIVITY_KEEPALIVE = "__AI_GOVERNESS_INTERNAL_STREAM_ACTIVITY__"


class BaseLLMClient(ABC):
    @abstractmethod
    async def send_message(self, text: str) -> AsyncGenerator[str, None]:
        """Send a message and stream text chunks through an async generator."""
        pass  # pragma: no cover

    @abstractmethod
    async def cancel(self):
        """Cancel the currently active request."""
        pass  # pragma: no cover

    async def refresh_session(self) -> bool:
        """
        Let the client rebuild its conversation session.

        This capability is optional; backends can keep the no-op default.
        """
        return False  # pragma: no cover

    async def ensure_ready(self) -> bool:
        """
        Pre-start any long-lived local backend resources.

        Stateless HTTP backends can keep the default no-op behavior. CLI-backed
        clients should override this so startup can block until the first real
        request will not pay the CLI/session cold-start cost.
        """
        return True  # pragma: no cover

    async def aclose(self):
        """Release resources such as subprocesses or background tasks."""
        pass  # pragma: no cover
