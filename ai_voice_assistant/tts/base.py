from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TTSPlaybackResult:
    played: bool
    backend: str
    reason: str | None = None
    error_type: str | None = None


class BaseTTSEngine(Protocol):
    async def speak_stream(
        self,
        text: str,
        audio_player,
        interrupt_signal: asyncio.Event | None = None,
    ) -> TTSPlaybackResult | None:
        ...

    def update_settings(self, **kwargs) -> None:
        ...

    def close(self) -> None:
        ...
