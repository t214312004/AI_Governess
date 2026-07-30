from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class OutputKind(str, Enum):
    TEXT = "text"
    ACTIVITY = "activity"
    USAGE = "usage"
    TOOL = "tool"
    CONTROL = "control"


@dataclass(frozen=True, slots=True)
class ProcessedOutput:
    kind: OutputKind
    text: str = ""
    metadata: dict[str, Any] | None = None

    @property
    def speakable(self) -> bool:
        return self.kind == OutputKind.TEXT and bool(self.text)


class LLMOutputProcessor:
    """Separate user text from activity, usage and tool protocol events."""

    _NON_TEXT_TYPES = {
        "activity": OutputKind.ACTIVITY,
        "usage": OutputKind.USAGE,
        "tool": OutputKind.TOOL,
        "tool_call": OutputKind.TOOL,
        "control": OutputKind.CONTROL,
    }

    def process(self, value: Any) -> ProcessedOutput:
        if isinstance(value, str):
            return ProcessedOutput(OutputKind.TEXT, value)
        if not isinstance(value, dict):
            return ProcessedOutput(OutputKind.CONTROL)

        event_type = str(value.get("type") or "text").strip().lower()
        kind = self._NON_TEXT_TYPES.get(event_type, OutputKind.TEXT)
        if kind != OutputKind.TEXT:
            return ProcessedOutput(kind, metadata=self._safe_metadata(value))
        text = value.get("text")
        return ProcessedOutput(OutputKind.TEXT, text if isinstance(text, str) else "")

    @staticmethod
    def _safe_metadata(value: dict[str, Any]) -> dict[str, Any]:
        allowed = {"type", "name", "status", "model", "input_tokens", "output_tokens"}
        return {key: value[key] for key in allowed if key in value}


class AdaptiveChunkPolicy:
    def __init__(
        self,
        *,
        split_punctuation: str = "。！？!?；;",
        min_first_chars: int = 12,
        min_chars: int = 20,
        max_chars: int = 80,
    ):
        self.split_punctuation = set(split_punctuation)
        self.min_first_chars = max(1, int(min_first_chars))
        self.min_chars = max(1, int(min_chars))
        self.max_chars = max(self.min_chars, int(max_chars))
        self.valid_pattern = re.compile(r"[^\W_]", re.UNICODE)
        self.buffer = ""
        self._emitted = 0
        self.queue_pressure = 0.0

    def set_queue_pressure(self, value: float) -> None:
        self.queue_pressure = min(1.0, max(0.0, float(value)))

    def _threshold(self) -> int:
        base = self.min_first_chars if self._emitted == 0 else self.min_chars
        return min(self.max_chars, int(round(base * (1.0 + self.queue_pressure))))

    def _next_chunk(self) -> str:
        threshold = self._threshold()
        for index, character in enumerate(self.buffer):
            if character in self.split_punctuation and index + 1 >= threshold:
                chunk = self.buffer[: index + 1]
                self.buffer = self.buffer[index + 1 :]
                return chunk

        if len(self.buffer) < self.max_chars:
            return ""
        cutoff = self.max_chars
        for index in range(self.max_chars - 1, threshold - 1, -1):
            if self.buffer[index].isspace() or self.buffer[index] in self.split_punctuation:
                cutoff = index + 1
                break
        chunk = self.buffer[:cutoff]
        self.buffer = self.buffer[cutoff:]
        return chunk

    def add_token(self, token: str):
        self.buffer += str(token or "")
        while True:
            chunk = self._next_chunk()
            if not chunk:
                return
            if self.valid_pattern.search(chunk):
                self._emitted += 1
                yield chunk.strip()

    def flush(self):
        if self.buffer:
            chunk = self.buffer
            self.buffer = ""
            if self.valid_pattern.search(chunk):
                self._emitted += 1
                yield chunk.strip()

    def reset(self):
        self.buffer = ""
        self._emitted = 0
        self.queue_pressure = 0.0
