from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Callable


_ALLOWED_POINTS = {
    "speech_started_at",
    "speech_ended_at",
    "endpoint_committed_at",
    "stt_started_at",
    "stt_completed_at",
    "llm_started_at",
    "llm_first_token_at",
    "tts_started_at",
    "tts_first_chunk_at",
    "playback_started_at",
    "cancel_requested_at",
    "software_silent_at",
    "acoustic_silent_at",
}


@dataclass(slots=True)
class TurnLatencyTrace:
    turn_id: str
    clock: Callable[[], float] = monotonic
    points: dict[str, float] = field(default_factory=dict)

    def mark(self, name: str, timestamp: float | None = None) -> float:
        if name not in _ALLOWED_POINTS:
            raise ValueError(f"Unsupported latency point: {name}")
        value = self.clock() if timestamp is None else float(timestamp)
        self.points.setdefault(name, value)
        return self.points[name]

    def duration_ms(self, start: str, end: str) -> float | None:
        if start not in self.points or end not in self.points:
            return None
        return max(0.0, (self.points[end] - self.points[start]) * 1000.0)

    def software_metrics(self) -> dict[str, float]:
        candidates = {
            "speech_end_to_endpoint_ms": ("speech_ended_at", "endpoint_committed_at"),
            "stt_ms": ("stt_started_at", "stt_completed_at"),
            "llm_first_token_ms": ("llm_started_at", "llm_first_token_at"),
            "tts_first_chunk_ms": ("tts_started_at", "tts_first_chunk_at"),
            "first_audio_e2e_ms": ("speech_ended_at", "playback_started_at"),
            "interruption_to_silence_ms": ("cancel_requested_at", "software_silent_at"),
        }
        result = {}
        for metric, (start, end) in candidates.items():
            value = self.duration_ms(start, end)
            if value is not None:
                result[metric] = value
        return result

    def redacted_snapshot(self) -> dict:
        return {
            "turn_id": self.turn_id,
            "points": dict(self.points),
            "metrics_ms": self.software_metrics(),
        }
