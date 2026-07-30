from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    streaming_input: bool = False
    streaming_output: bool = False
    physical_cancel: bool = False
    partial_results: bool = False
    tool_suppression: bool = False
    read_only_session: bool = False
    side_effect_free_speculation: bool = False


@dataclass(frozen=True, slots=True)
class BackendHealth:
    ready: bool
    backend: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class BackendRegistration(Generic[T]):
    canonical_id: str
    factory: Callable[..., T]
    capabilities: BackendCapabilities


class BackendRegistry(Generic[T]):
    def __init__(self, kind: str):
        self.kind = str(kind)
        self._registrations: dict[str, BackendRegistration[T]] = {}
        self._aliases: dict[str, str] = {}

    @staticmethod
    def _normalize(value: str) -> str:
        return str(value or "").strip().lower().replace("-", "_")

    def register(
        self,
        backend_id: str,
        factory: Callable[..., T],
        *,
        aliases: tuple[str, ...] = (),
        capabilities: BackendCapabilities | None = None,
    ) -> None:
        canonical = self._normalize(backend_id)
        if not canonical:
            raise ValueError("backend_id is required")
        if canonical in self._registrations:
            raise ValueError(f"Duplicate {self.kind} backend: {canonical}")
        self._registrations[canonical] = BackendRegistration(
            canonical,
            factory,
            capabilities or BackendCapabilities(),
        )
        for alias in aliases:
            normalized = self._normalize(alias)
            if normalized and normalized != canonical:
                self._aliases[normalized] = canonical

    def resolve(self, backend_id: str) -> BackendRegistration[T]:
        requested = self._normalize(backend_id)
        canonical = self._aliases.get(requested, requested)
        try:
            return self._registrations[canonical]
        except KeyError as exc:
            raise KeyError(f"Unknown {self.kind} backend: {backend_id}") from exc

    def create(self, backend_id: str, **kwargs: Any) -> T:
        return self.resolve(backend_id).factory(**kwargs)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._registrations))
