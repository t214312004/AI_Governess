import queue

import pytest

from core.pipeline.cancellation import CancelDisposition, CancelScope
from core.pipeline.latency import TurnLatencyTrace
from core.pipeline.output_processor import AdaptiveChunkPolicy, LLMOutputProcessor, OutputKind
from core.pipeline.queueing import BoundedStageQueue, OverflowPolicy
from core.pipeline.registry import BackendCapabilities, BackendRegistry


def test_cancel_scope_distinguishes_logical_and_already_cancelled():
    scope = CancelScope(3)

    first = scope.cancel("interrupt")
    second = scope.cancel("again")

    assert first.disposition == CancelDisposition.LOGICAL
    assert first.prevents_stale_output is True
    assert second.disposition == CancelDisposition.ALREADY_CANCELLED
    assert second.reason == "interrupt"


def test_cancel_scope_reports_physical_cancel_when_callback_confirms():
    scope = CancelScope(1)
    scope.register(lambda _reason: True)

    result = scope.cancel("stop", physical_supported=True)

    assert result.disposition == CancelDisposition.PHYSICAL


def test_bounded_queue_rejects_newest_and_records_watermark():
    stage_queue = BoundedStageQueue(2, OverflowPolicy.REJECT)
    assert stage_queue.offer("a").accepted is True
    assert stage_queue.offer("b").accepted is True

    rejected = stage_queue.offer("c")

    assert rejected.accepted is False
    assert stage_queue.high_watermark == 2
    assert stage_queue.dropped_count == 1


def test_bounded_queue_drop_oldest_preserves_new_order():
    stage_queue = BoundedStageQueue(2, OverflowPolicy.DROP_OLDEST)
    stage_queue.offer("a")
    stage_queue.offer("b")

    result = stage_queue.offer("c")

    assert result.dropped == 1
    assert stage_queue.drain() == ["b", "c"]


def test_backend_registry_resolves_alias_and_capabilities():
    registry = BackendRegistry("tts")
    registry.register(
        "edge",
        lambda value=1: value,
        aliases=("edge-tts",),
        capabilities=BackendCapabilities(streaming_output=True),
    )

    registration = registry.resolve("edge-tts")

    assert registration.canonical_id == "edge"
    assert registration.capabilities.streaming_output is True
    assert registry.create("edge", value=7) == 7


def test_backend_registry_rejects_unknown_backend():
    registry = BackendRegistry("stt")

    with pytest.raises(KeyError, match="Unknown stt backend"):
        registry.resolve("missing")


def test_output_processor_never_marks_tool_or_usage_as_speakable():
    processor = LLMOutputProcessor()

    tool = processor.process({"type": "tool_call", "name": "write", "arguments": "secret"})
    usage = processor.process({"type": "usage", "input_tokens": 3, "prompt": "secret"})

    assert tool.kind == OutputKind.TOOL and tool.speakable is False
    assert usage.kind == OutputKind.USAGE and usage.speakable is False
    assert "arguments" not in tool.metadata
    assert "prompt" not in usage.metadata


def test_adaptive_chunk_policy_emits_early_first_sentence_and_bounds_long_text():
    policy = AdaptiveChunkPolicy(min_first_chars=4, min_chars=6, max_chars=10)

    first = list(policy.add_token("你好嗎？後面還有一段很長的文字"))
    remainder = list(policy.flush())

    assert first[0] == "你好嗎？"
    assert all(len(chunk) <= 10 for chunk in first)
    assert remainder


def test_adaptive_chunk_policy_coalesces_more_under_pressure():
    policy = AdaptiveChunkPolicy(min_first_chars=4, min_chars=4, max_chars=20)
    policy.set_queue_pressure(1.0)

    chunks = list(policy.add_token("短句。第二句足夠長。"))

    assert chunks == ["短句。第二句足夠長。"]


def test_latency_trace_uses_non_content_snapshot_and_consistent_milliseconds():
    values = iter([1.0, 1.25])
    trace = TurnLatencyTrace("turn-1", clock=lambda: next(values))
    trace.mark("speech_ended_at")
    trace.mark("playback_started_at")

    snapshot = trace.redacted_snapshot()

    assert snapshot["metrics_ms"]["first_audio_e2e_ms"] == pytest.approx(250.0)
    assert set(snapshot) == {"turn_id", "points", "metrics_ms"}
