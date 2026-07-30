from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.pipeline.registry import BackendCapabilities, BackendRegistry


def _stt_factory(backend_id: str):
    def create(**kwargs):
        from core.transcriber import BackgroundTranscriber

        return BackgroundTranscriber(backend=backend_id, **kwargs)

    return create


def _llm_factory(backend_id: str):
    def create(**kwargs):
        from llm.client_factory import create_llm_client

        return create_llm_client(backend_id, **kwargs)

    return create


def _tts_factory(backend_id: str):
    def create(**kwargs):
        if backend_id == "edge":
            from tts.edge_tts_engine import EdgeTTSEngine

            return EdgeTTSEngine(**kwargs)
        from tts.bluemagpie_tts_engine import BlueMagpieTTSEngine

        return BlueMagpieTTSEngine(**kwargs)

    return create


@dataclass(frozen=True, slots=True)
class BackendSelection:
    stt: str
    llm: str
    tts: str


class PipelineBackendCatalog:
    """Canonical, independently resolvable STT/LLM/TTS registrations.

    Registrations use lazy factories so selecting or validating one backend
    never imports or starts an unrelated backend.
    """

    def __init__(self):
        self.stt: BackendRegistry[Any] = BackendRegistry("stt")
        self.llm: BackendRegistry[Any] = BackendRegistry("llm")
        self.tts: BackendRegistry[Any] = BackendRegistry("tts")
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.stt.register(
            "local",
            _stt_factory("local"),
            aliases=("faster_whisper", "faster-whisper", "whisper"),
            capabilities=BackendCapabilities(),
        )
        self.stt.register(
            "groq",
            _stt_factory("groq"),
            capabilities=BackendCapabilities(),
        )

        for backend_id in (
            "claude_code",
            "codex_cli",
            "opencode_cli",
            "grok_cli",
            "antigravity_cli",
        ):
            self.llm.register(
                backend_id,
                _llm_factory(backend_id),
                aliases=(backend_id.replace("_", "-"),),
                capabilities=BackendCapabilities(
                    streaming_output=True,
                    tool_suppression=True,
                ),
            )

        self.tts.register(
            "edge",
            _tts_factory("edge"),
            aliases=("edge_tts", "edge-tts"),
            capabilities=BackendCapabilities(streaming_output=True),
        )
        self.tts.register(
            "bluemagpie",
            _tts_factory("bluemagpie"),
            aliases=("blue_magpie", "blue-magpie", "bluemagpie_tts", "bluemagpie-tts"),
            capabilities=BackendCapabilities(streaming_output=True),
        )

    def resolve_selection(self, *, stt: str, llm: str, tts: str) -> BackendSelection:
        return BackendSelection(
            stt=self.stt.resolve(stt).canonical_id,
            llm=self.llm.resolve(llm).canonical_id,
            tts=self.tts.resolve(tts).canonical_id,
        )

    def diagnostic_snapshot(self, selection: BackendSelection | None = None) -> dict:
        result = {
            "registered": {
                "stt": self.stt.ids(),
                "llm": self.llm.ids(),
                "tts": self.tts.ids(),
            }
        }
        if selection is not None:
            result["selected"] = {
                "stt": selection.stt,
                "llm": selection.llm,
                "tts": selection.tts,
            }
        return result
