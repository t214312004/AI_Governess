from __future__ import annotations

from core.pipeline.runtime import PipelineRuntime


class PipelineCoordinator(PipelineRuntime):
    """Application-neutral owner of Turn arbitration and lifecycle state."""
