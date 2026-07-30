from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import AsyncIterator, Protocol

from core.audio_player import PlaybackChunk


@dataclass(frozen=True, slots=True)
class TTSPlaybackResult:
    played: bool
    backend: str
    reason: str | None = None
    error_type: str | None = None


class PlaybackChunkCollector:
    """Compatibility sink used by adapters while the v2.5 path owns playback."""

    def __init__(
        self,
        sample_rate: int,
        *,
        response_generation: int | None = None,
        turn_id: str | None = None,
    ):
        self.sample_rate = int(sample_rate)
        self.response_generation = response_generation
        self.turn_id = turn_id
        self.chunks: list[PlaybackChunk] = []

    def play(self, chunk) -> bool:
        if isinstance(chunk, PlaybackChunk):
            chunk = replace(
                chunk,
                response_generation=self.response_generation,
                turn_id=self.turn_id,
            )
        else:
            chunk = PlaybackChunk(
                pcm_data=chunk,
                response_generation=self.response_generation,
                turn_id=self.turn_id,
            )
        self.chunks.append(chunk)
        return True


class BaseTTSEngine(Protocol):
    async def synthesize_stream(
        self,
        text: str,
        interrupt_signal: asyncio.Event | None = None,
        *,
        response_generation: int | None = None,
        turn_id: str | None = None,
    ) -> AsyncIterator[PlaybackChunk]:
        ...

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
