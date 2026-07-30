from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from types import MappingProxyType
from typing import Any, Mapping, NewType
from uuid import uuid4


ResponseGeneration = NewType("ResponseGeneration", int)
AudioCaptureEpoch = NewType("AudioCaptureEpoch", int)
BackendInstanceGeneration = NewType("BackendInstanceGeneration", int)


class TurnSource(str, Enum):
    VOICE = "voice"
    TEXT = "text"
    HEARTBEAT = "heartbeat"
    SCHEDULE = "schedule"
    INTERRUPT = "interrupt"
    SHUTDOWN = "shutdown"

    @classmethod
    def coerce(cls, value: str | TurnSource | None) -> TurnSource:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value or "voice").strip().lower())
        except ValueError:
            return cls.VOICE


@dataclass(frozen=True, slots=True)
class TurnContext:
    turn_id: str
    source: TurnSource
    response_generation: ResponseGeneration
    audio_capture_epoch: AudioCaptureEpoch
    backend_instance_generation: BackendInstanceGeneration
    created_at: float = field(default_factory=monotonic)
    request_id: str | None = None
    config_snapshot: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    @classmethod
    def create(
        cls,
        *,
        source: TurnSource,
        response_generation: int,
        audio_capture_epoch: int,
        backend_instance_generation: int,
        request_id: str | None = None,
        config_snapshot: Mapping[str, Any] | None = None,
    ) -> TurnContext:
        return cls(
            turn_id=uuid4().hex,
            source=source,
            response_generation=ResponseGeneration(response_generation),
            audio_capture_epoch=AudioCaptureEpoch(audio_capture_epoch),
            backend_instance_generation=BackendInstanceGeneration(
                backend_instance_generation
            ),
            request_id=request_id,
            config_snapshot=MappingProxyType(dict(config_snapshot or {})),
        )


@dataclass(frozen=True, slots=True)
class TranscriptionEvent:
    turn_id: str
    revision: int
    text: str
    is_final: bool
    response_generation: ResponseGeneration


@dataclass(frozen=True, slots=True)
class LLMToken:
    turn_id: str
    text: str
    response_generation: ResponseGeneration


@dataclass(frozen=True, slots=True)
class TextChunk:
    turn_id: str
    text: str
    chunk_index: int
    response_generation: ResponseGeneration
    is_final: bool = False


@dataclass(frozen=True, slots=True)
class AudioChunk:
    turn_id: str
    pcm_data: Any
    sample_rate: int
    channels: int
    chunk_index: int
    response_generation: ResponseGeneration
    is_final: bool = False
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, slots=True)
class ControlEvent:
    name: str
    response_generation: ResponseGeneration
    reason: str | None = None
