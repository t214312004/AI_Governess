from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_TIMEZONE = "Asia/Taipei"
DEFAULT_DRAFT_TTL_SECONDS = 20 * 60
DEFAULT_UNDO_SECONDS = 2 * 60
DEFAULT_CLAIM_TIMEOUT_SECONDS = 10 * 60

SCHEDULE_STATUS_SCHEDULED = "scheduled"
SCHEDULE_STATUS_CLAIMED = "claimed"
SCHEDULE_STATUS_DISABLED = "disabled"
SCHEDULE_STATUS_COMPLETED = "completed"
SCHEDULE_STATUS_DELAYED = "delayed"
SCHEDULE_STATUS_MISSED = "missed"
SCHEDULE_STATUS_NEEDS_ATTENTION = "needs_attention"

RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_INTERRUPTED = "interrupted"
RUN_STATUS_DEFERRED = "deferred"
RUN_STATUS_MISSED = "missed"

TOOL_STATUS_CREATED = "created"
TOOL_STATUS_UPDATED = "updated"
TOOL_STATUS_DELETED = "deleted"
TOOL_STATUS_DISABLED = "disabled"
TOOL_STATUS_ENABLED = "enabled"
TOOL_STATUS_LISTED = "listed"
TOOL_STATUS_CANCELLED = "cancelled"
TOOL_STATUS_NEEDS_CLARIFICATION = "needs_clarification"
TOOL_STATUS_NEEDS_CONFIRMATION = "needs_confirmation"
TOOL_STATUS_NEEDS_SELECTION = "needs_selection"
TOOL_STATUS_BLOCKED = "blocked"
TOOL_STATUS_ERROR = "error"

VALID_TRIGGER_TYPES = {"once", "daily", "weekly", "interval"}
VALID_MISS_POLICIES = {"skip", "run_late", "defer_until_idle"}
PARENT_SPEAKERS = {"thomas", "vivi"}


class ScheduleValidationError(ValueError):
    """Raised when schedule input cannot be safely written."""

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        user_message: str | None = None,
    ):
        super().__init__(message)
        self.field = field
        self.user_message = user_message or message


@dataclass(slots=True)
class DueScheduleClaim:
    schedule_id: str
    claim_id: str
    schedule: dict[str, Any]
    claimed_at: datetime
