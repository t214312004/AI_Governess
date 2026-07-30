"""Composable v2.5 voice-pipeline primitives.

This package intentionally has no UI imports and no dependency on
``VoiceAssistant``.  The existing class remains the public facade while these
objects own turn identity, cancellation, arbitration and bounded stage state.
"""

from core.pipeline.arbitration import ArbitrationAction, ArbitrationDecision, TurnArbitrationPolicy
from core.pipeline.cancellation import CancelDisposition, CancelResult, CancelScope
from core.pipeline.backends import BackendSelection, PipelineBackendCatalog
from core.pipeline.composition import PipelineComposition, PipelineCompositionRoot
from core.pipeline.coordinator import PipelineCoordinator
from core.pipeline.messages import (
    AudioChunk,
    BackendInstanceGeneration,
    ControlEvent,
    LLMToken,
    ResponseGeneration,
    TextChunk,
    TranscriptionEvent,
    TurnContext,
    TurnSource,
)
from core.pipeline.runtime import PipelineRuntime, PipelineSettings, RuntimeMode, RuntimeSelector

__all__ = [
    "ArbitrationAction",
    "ArbitrationDecision",
    "AudioChunk",
    "BackendSelection",
    "BackendInstanceGeneration",
    "CancelDisposition",
    "CancelResult",
    "CancelScope",
    "ControlEvent",
    "LLMToken",
    "PipelineRuntime",
    "PipelineBackendCatalog",
    "PipelineComposition",
    "PipelineCompositionRoot",
    "PipelineCoordinator",
    "PipelineSettings",
    "ResponseGeneration",
    "RuntimeMode",
    "RuntimeSelector",
    "TextChunk",
    "TranscriptionEvent",
    "TurnArbitrationPolicy",
    "TurnContext",
    "TurnSource",
]
