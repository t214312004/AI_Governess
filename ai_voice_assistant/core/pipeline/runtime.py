from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from core.pipeline.arbitration import ArbitrationDecision, TurnArbitrationPolicy
from core.pipeline.cancellation import CancelResult, CancelScope
from core.pipeline.latency import TurnLatencyTrace
from core.pipeline.messages import TurnContext, TurnSource


_MAX_RETAINED_TRACES = 256


class RuntimeMode(str, Enum):
    V2_5 = "v2_5"


@dataclass(frozen=True, slots=True)
class PipelineSettings:
    progressive_transcription: bool = False
    revision_aware_endpoint: bool = True
    streaming_tts: bool = False
    adaptive_chunking: bool = False
    parallel_speaker: bool = False
    metrics_enabled: bool = True
    playback_queue_chunks: int = 128
    tts_queue_chunks: int = 8

    @staticmethod
    def _bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off", ""}:
                return False
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        # Configuration proxies and mocks must never opt in implicitly.
        return default

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> PipelineSettings:
        raw = dict(value or {})
        settings = cls(
            progressive_transcription=cls._bool(raw.get("progressive_transcription")),
            revision_aware_endpoint=cls._bool(raw.get("revision_aware_endpoint"), True),
            streaming_tts=cls._bool(raw.get("streaming_tts")),
            adaptive_chunking=cls._bool(raw.get("adaptive_chunking")),
            parallel_speaker=cls._bool(raw.get("parallel_speaker")),
            metrics_enabled=cls._bool(raw.get("metrics_enabled"), True),
            playback_queue_chunks=max(4, int(raw.get("playback_queue_chunks", 128))),
            tts_queue_chunks=max(1, int(raw.get("tts_queue_chunks", 8))),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.progressive_transcription and not self.revision_aware_endpoint:
            raise ValueError(
                "progressive_transcription requires revision_aware_endpoint"
            )
@dataclass(frozen=True, slots=True)
class RuntimeSelection:
    mode: RuntimeMode
    settings: PipelineSettings


class RuntimeSelector:
    @staticmethod
    def resolve(config_provider) -> RuntimeSelection:
        defaults = {
            "progressive_transcription": False,
            "revision_aware_endpoint": True,
            "streaming_tts": False,
            "adaptive_chunking": False,
            "parallel_speaker": False,
            "metrics_enabled": True,
            "playback_queue_chunks": 128,
            "tts_queue_chunks": 8,
        }
        raw = {
            key: config_provider.get("pipeline_v2_5", key, default=default)
            for key, default in defaults.items()
        }
        settings = PipelineSettings.from_mapping(raw)
        return RuntimeSelection(RuntimeMode.V2_5, settings)


@dataclass(slots=True)
class TurnLease:
    context: TurnContext
    cancel_scope: CancelScope
    trace: TurnLatencyTrace | None


@dataclass(frozen=True, slots=True)
class TurnStartResult:
    decision: ArbitrationDecision
    lease: TurnLease | None
    preempted: TurnContext | None = None


@dataclass(frozen=True, slots=True)
class TurnMetricRecord:
    turn_id: str
    outcome: str
    snapshot: dict


class PipelineRuntime:
    """Owns identity and arbitration without importing UI/application classes."""

    def __init__(self, selection: RuntimeSelection):
        self.selection = selection
        self.policy = TurnArbitrationPolicy()
        self._lock = threading.RLock()
        self._response_generation = 0
        self._audio_capture_epoch = 0
        self._backend_instance_generation = 0
        self._active: TurnLease | None = None
        self._traces: dict[str, TurnLatencyTrace] = {}
        self._terminal_outcomes: dict[str, str] = {}
        self._emitted_trace_ids: set[str] = set()
        self._last_cancelled_turn_id: str | None = None
        self._closed = False

    @property
    def active(self) -> TurnLease | None:
        with self._lock:
            return self._active

    @property
    def response_generation(self) -> int:
        with self._lock:
            return self._response_generation

    def _prune_turn_history_locked(self) -> None:
        while len(self._terminal_outcomes) > _MAX_RETAINED_TRACES:
            oldest_turn_id = next(iter(self._terminal_outcomes))
            self._terminal_outcomes.pop(oldest_turn_id, None)
            self._traces.pop(oldest_turn_id, None)
            self._emitted_trace_ids.discard(oldest_turn_id)

    def begin_turn(
        self,
        source: TurnSource | str,
        *,
        request_id: str | None = None,
        config_snapshot: Mapping[str, Any] | None = None,
    ) -> TurnStartResult:
        source = TurnSource.coerce(source)
        with self._lock:
            if self._closed:
                raise RuntimeError("Pipeline runtime is closed")
            active_context = self._active.context if self._active else None
            decision = self.policy.decide(active_context, source)
            if not decision.accepted:
                return TurnStartResult(decision, None)

            preempted = active_context
            if self._active is not None:
                preempted_turn_id = self._active.context.turn_id
                self._active.cancel_scope.cancel(decision.reason)
                self._terminal_outcomes[preempted_turn_id] = "preempted"
                self._prune_turn_history_locked()

            self._response_generation += 1
            context = TurnContext.create(
                source=source,
                response_generation=self._response_generation,
                audio_capture_epoch=self._audio_capture_epoch,
                backend_instance_generation=self._backend_instance_generation,
                request_id=request_id,
                config_snapshot=MappingProxyType(dict(config_snapshot or {})),
            )
            trace = (
                TurnLatencyTrace(context.turn_id)
                if self.selection.settings.metrics_enabled
                else None
            )
            lease = TurnLease(context, CancelScope(self._response_generation), trace)
            self._active = lease
            if trace is not None:
                self._traces[context.turn_id] = trace
                while len(self._traces) > _MAX_RETAINED_TRACES:
                    oldest_turn_id = next(iter(self._traces))
                    self._traces.pop(oldest_turn_id, None)
                    self._terminal_outcomes.pop(oldest_turn_id, None)
                    self._emitted_trace_ids.discard(oldest_turn_id)
            return TurnStartResult(decision, lease, preempted)

    def cancel_active(self, reason: str) -> CancelResult | None:
        with self._lock:
            if self._active is None:
                self._last_cancelled_turn_id = None
                self._response_generation += 1
                return None
            self._last_cancelled_turn_id = self._active.context.turn_id
            result = self._active.cancel_scope.cancel(reason)
            self._terminal_outcomes[self._last_cancelled_turn_id] = "cancelled"
            self._prune_turn_history_locked()
            self._response_generation += 1
            self._active = None
            return result

    def complete(self, turn_id: str, *, outcome: str = "completed") -> bool:
        with self._lock:
            if self._active is None or self._active.context.turn_id != turn_id:
                return False
            self._terminal_outcomes[turn_id] = str(outcome or "completed")
            self._prune_turn_history_locked()
            self._active = None
            return True

    def terminal_outcome(self, turn_id: str) -> str | None:
        with self._lock:
            return self._terminal_outcomes.get(turn_id)

    def consume_metric_record(self, turn_id: str) -> TurnMetricRecord | None:
        """Return one terminal trace record at most once per Turn."""
        with self._lock:
            if turn_id in self._emitted_trace_ids:
                return None
            outcome = self._terminal_outcomes.get(turn_id)
            trace = self._traces.get(turn_id)
            if outcome is None or trace is None:
                return None
            self._emitted_trace_ids.add(turn_id)
            return TurnMetricRecord(
                turn_id=turn_id,
                outcome=outcome,
                snapshot=trace.redacted_snapshot(),
            )

    def advance_audio_capture_epoch(self) -> int:
        with self._lock:
            self._audio_capture_epoch += 1
            return self._audio_capture_epoch

    def advance_backend_instance_generation(self) -> int:
        with self._lock:
            self._backend_instance_generation += 1
            return self._backend_instance_generation

    def trace_snapshot(self, turn_id: str) -> dict | None:
        with self._lock:
            trace = self._traces.get(turn_id)
            return trace.redacted_snapshot() if trace is not None else None

    def mark(self, name: str, *, timestamp: float | None = None) -> float | None:
        with self._lock:
            if self._active is None or self._active.trace is None:
                return None
            return self._active.trace.mark(name, timestamp)

    @property
    def last_cancelled_turn_id(self) -> str | None:
        with self._lock:
            return self._last_cancelled_turn_id

    def mark_turn(
        self,
        turn_id: str,
        name: str,
        *,
        timestamp: float | None = None,
    ) -> float | None:
        with self._lock:
            trace = self._traces.get(turn_id)
            return trace.mark(name, timestamp) if trace is not None else None

    def diagnostic_snapshot(self) -> dict:
        with self._lock:
            active = self._active.context if self._active else None
            return {
                "mode": self.selection.mode.value,
                "active_turn_id": active.turn_id if active else None,
                "active_source": active.source.value if active else None,
                "response_generation": self._response_generation,
                "audio_capture_epoch": self._audio_capture_epoch,
                "backend_instance_generation": self._backend_instance_generation,
                "retained_trace_count": len(self._traces),
                "terminal_outcome_count": len(self._terminal_outcomes),
                "emitted_trace_count": len(self._emitted_trace_ids),
                "closed": self._closed,
            }

    def close(self) -> None:
        with self._lock:
            if self._active is not None:
                self._terminal_outcomes[self._active.context.turn_id] = "shutdown"
                self._prune_turn_history_locked()
                self._active.cancel_scope.cancel("shutdown")
                self._active = None
            self._closed = True
