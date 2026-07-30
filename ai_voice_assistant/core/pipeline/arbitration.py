from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.pipeline.messages import TurnContext, TurnSource


class ArbitrationAction(str, Enum):
    ACCEPT = "accept"
    PREEMPT = "preempt"
    REJECT_BUSY = "reject_busy"
    COALESCE = "coalesce"


@dataclass(frozen=True, slots=True)
class ArbitrationDecision:
    action: ArbitrationAction
    reason: str
    requires_claim_compensation: bool = False

    @property
    def accepted(self) -> bool:
        return self.action in {ArbitrationAction.ACCEPT, ArbitrationAction.PREEMPT}


class TurnArbitrationPolicy:
    """One explicit policy for voice, text and background turn ownership."""

    _PRIORITY = {
        TurnSource.HEARTBEAT: 10,
        TurnSource.SCHEDULE: 20,
        TurnSource.TEXT: 40,
        TurnSource.VOICE: 40,
        TurnSource.INTERRUPT: 90,
        TurnSource.SHUTDOWN: 100,
    }

    def decide(
        self,
        active: TurnContext | None,
        incoming: TurnSource | str,
    ) -> ArbitrationDecision:
        incoming = TurnSource.coerce(incoming)
        if active is None:
            return ArbitrationDecision(ArbitrationAction.ACCEPT, "idle")

        active_source = active.source
        if incoming == active_source and incoming in {
            TurnSource.HEARTBEAT,
            TurnSource.SCHEDULE,
        }:
            return ArbitrationDecision(ArbitrationAction.COALESCE, "background_duplicate")
        if incoming == TurnSource.HEARTBEAT:
            return ArbitrationDecision(ArbitrationAction.REJECT_BUSY, "background_busy")

        incoming_priority = self._PRIORITY[incoming]
        active_priority = self._PRIORITY[active_source]
        if incoming_priority > active_priority:
            return ArbitrationDecision(
                ArbitrationAction.PREEMPT,
                f"{incoming.value}_preempts_{active_source.value}",
                requires_claim_compensation=active_source == TurnSource.SCHEDULE,
            )

        return ArbitrationDecision(
            ArbitrationAction.REJECT_BUSY,
            f"{active_source.value}_owns_runtime",
        )
