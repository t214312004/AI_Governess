from __future__ import annotations

from dataclasses import dataclass

from core.pipeline.backends import BackendSelection, PipelineBackendCatalog
from core.pipeline.coordinator import PipelineCoordinator
from core.pipeline.runtime import RuntimeSelection, RuntimeSelector


@dataclass(frozen=True, slots=True)
class PipelineComposition:
    selection: RuntimeSelection
    coordinator: PipelineCoordinator
    backend_catalog: PipelineBackendCatalog
    backend_selection: BackendSelection


class PipelineCompositionRoot:
    """Creates exactly one selected runtime before heavyweight resources."""

    @staticmethod
    def build(config_provider) -> PipelineComposition:
        selection = RuntimeSelector.resolve(config_provider)
        coordinator = PipelineCoordinator(selection)
        catalog = PipelineBackendCatalog()
        backend_selection = catalog.resolve_selection(
            stt=config_provider.get("whisper", "backend", default="local") or "local",
            llm=config_provider.get(
                "llm", "active_backend", default="antigravity_cli"
            )
            or "antigravity_cli",
            tts=config_provider.get("tts", "backend", default="edge") or "edge",
        )
        return PipelineComposition(
            selection=selection,
            coordinator=coordinator,
            backend_catalog=catalog,
            backend_selection=backend_selection,
        )
