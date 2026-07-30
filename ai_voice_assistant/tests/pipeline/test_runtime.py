import pytest

from core.pipeline.arbitration import ArbitrationAction, TurnArbitrationPolicy
from core.pipeline.backends import PipelineBackendCatalog
from core.pipeline.composition import PipelineCompositionRoot
from core.pipeline.coordinator import PipelineCoordinator
from core.pipeline.messages import TurnContext, TurnSource
from core.pipeline.runtime import (
    PipelineRuntime,
    PipelineSettings,
    RuntimeMode,
    RuntimeSelection,
    RuntimeSelector,
)


class DictConfig:
    def __init__(self, values):
        self.values = values

    def get(self, *keys, default=None):
        value = self.values
        for key in keys:
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]
        return value


def _context(source):
    return TurnContext.create(
        source=source,
        response_generation=1,
        audio_capture_epoch=0,
        backend_instance_generation=0,
    )


def test_runtime_selector_defaults_to_v25_without_an_enable_flag():
    selection = RuntimeSelector.resolve(DictConfig({}))

    assert selection.mode == RuntimeMode.V2_5


def test_runtime_selector_reads_v25_optimization_settings():
    selection = RuntimeSelector.resolve(
        DictConfig({"pipeline_v2_5": {"adaptive_chunking": True}})
    )

    assert selection.mode == RuntimeMode.V2_5
    assert selection.settings.adaptive_chunking is True


def test_composition_root_builds_one_coordinator_and_canonical_backends():
    composition = PipelineCompositionRoot.build(
        DictConfig(
            {
                "whisper": {"backend": "faster-whisper"},
                "llm": {"active_backend": "codex-cli"},
                "tts": {"backend": "edge-tts"},
            }
        )
    )

    assert isinstance(composition.coordinator, PipelineCoordinator)
    assert composition.coordinator.selection is composition.selection
    assert composition.backend_selection.stt == "local"
    assert composition.backend_selection.llm == "codex_cli"
    assert composition.backend_selection.tts == "edge"


def test_backend_catalogs_are_independent_and_fail_closed():
    catalog = PipelineBackendCatalog()

    assert catalog.stt.ids() == ("groq", "local")
    assert "codex_cli" in catalog.llm.ids()
    assert catalog.tts.resolve("blue-magpie").canonical_id == "bluemagpie"
    with pytest.raises(KeyError, match="Unknown llm backend"):
        catalog.resolve_selection(stt="local", llm="unknown", tts="edge")


def test_feature_dependency_validation_fails_closed():
    with pytest.raises(ValueError, match="revision_aware_endpoint"):
        PipelineSettings.from_mapping(
            {
                "progressive_transcription": True,
                "revision_aware_endpoint": False,
            }
        )


@pytest.mark.parametrize("source", [TurnSource.VOICE, TurnSource.TEXT])
def test_user_turn_preempts_heartbeat(source):
    decision = TurnArbitrationPolicy().decide(_context(TurnSource.HEARTBEAT), source)

    assert decision.action == ArbitrationAction.PREEMPT


def test_user_turn_preempts_schedule_with_compensation_requirement():
    decision = TurnArbitrationPolicy().decide(
        _context(TurnSource.SCHEDULE),
        TurnSource.VOICE,
    )

    assert decision.action == ArbitrationAction.PREEMPT
    assert decision.requires_claim_compensation is True


def test_background_turn_does_not_preempt_user_turn():
    decision = TurnArbitrationPolicy().decide(
        _context(TurnSource.TEXT),
        TurnSource.HEARTBEAT,
    )

    assert decision.action == ArbitrationAction.REJECT_BUSY


def test_runtime_generations_and_stale_completion_are_isolated():
    runtime = PipelineRuntime(
        RuntimeSelection(RuntimeMode.V2_5, PipelineSettings())
    )
    first = runtime.begin_turn(TurnSource.HEARTBEAT)
    second = runtime.begin_turn(TurnSource.VOICE)

    assert first.lease is not None
    assert second.lease is not None
    assert first.lease.cancel_scope.is_cancelled is True
    assert int(second.lease.context.response_generation) == 2
    assert runtime.complete(first.lease.context.turn_id) is False
    assert runtime.complete(second.lease.context.turn_id) is True


def test_cancelled_turn_metric_record_is_terminal_and_consumed_once():
    runtime = PipelineRuntime(
        RuntimeSelection(RuntimeMode.V2_5, PipelineSettings())
    )
    started = runtime.begin_turn(TurnSource.VOICE)
    turn_id = started.lease.context.turn_id
    runtime.mark("cancel_requested_at", timestamp=10.0)

    runtime.cancel_active("interrupt")
    runtime.mark_turn(turn_id, "software_silent_at", timestamp=10.025)

    assert runtime.complete(turn_id) is False
    record = runtime.consume_metric_record(turn_id)
    assert record.outcome == "cancelled"
    assert record.snapshot["metrics_ms"]["interruption_to_silence_ms"] == pytest.approx(25.0)
    assert runtime.consume_metric_record(turn_id) is None


def test_cancel_without_active_turn_does_not_reuse_previous_turn_id():
    runtime = PipelineRuntime(
        RuntimeSelection(RuntimeMode.V2_5, PipelineSettings())
    )
    started = runtime.begin_turn(TurnSource.VOICE)

    runtime.cancel_active("first interrupt")
    assert runtime.last_cancelled_turn_id == started.lease.context.turn_id

    assert runtime.cancel_active("late duplicate interrupt") is None
    assert runtime.last_cancelled_turn_id is None


def test_preempted_turn_preserves_terminal_outcome_for_late_owner_cleanup():
    runtime = PipelineRuntime(
        RuntimeSelection(RuntimeMode.V2_5, PipelineSettings())
    )
    heartbeat = runtime.begin_turn(TurnSource.HEARTBEAT)
    voice = runtime.begin_turn(TurnSource.VOICE)

    assert voice.lease is not None
    assert runtime.complete(heartbeat.lease.context.turn_id) is False
    record = runtime.consume_metric_record(heartbeat.lease.context.turn_id)
    assert record.outcome == "preempted"
    assert runtime.consume_metric_record(heartbeat.lease.context.turn_id) is None


def test_runtime_diagnostic_snapshot_contains_no_user_content():
    runtime = PipelineRuntime(
        RuntimeSelection(RuntimeMode.V2_5, PipelineSettings())
    )
    started = runtime.begin_turn(
        TurnSource.TEXT,
        request_id="request-1",
        config_snapshot={"llm": "test"},
    )

    snapshot = runtime.diagnostic_snapshot()

    assert snapshot["active_turn_id"] == started.lease.context.turn_id
    assert "prompt" not in snapshot
    assert "text" not in snapshot


def test_runtime_bounds_completed_trace_retention():
    runtime = PipelineRuntime(
        RuntimeSelection(RuntimeMode.V2_5, PipelineSettings())
    )

    for index in range(300):
        started = runtime.begin_turn(TurnSource.TEXT, request_id=f"request-{index}")
        runtime.complete(started.lease.context.turn_id)

    snapshot = runtime.diagnostic_snapshot()
    assert snapshot["retained_trace_count"] == 256
    assert snapshot["terminal_outcome_count"] == 256
