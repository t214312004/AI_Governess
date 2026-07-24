from __future__ import annotations

import contextlib
import json
import os
import re
import uuid
import unicodedata
from copy import deepcopy
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python always has zoneinfo in supported runtimes.
    ZoneInfo = None

from core.schedule_models import (
    DEFAULT_CLAIM_TIMEOUT_SECONDS,
    DEFAULT_DRAFT_TTL_SECONDS,
    DEFAULT_TIMEZONE,
    DEFAULT_UNDO_SECONDS,
    PARENT_SPEAKERS,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_INTERRUPTED,
    RUN_STATUS_MISSED,
    SCHEMA_VERSION,
    SCHEDULE_STATUS_CLAIMED,
    SCHEDULE_STATUS_COMPLETED,
    SCHEDULE_STATUS_DELAYED,
    SCHEDULE_STATUS_DISABLED,
    SCHEDULE_STATUS_MISSED,
    SCHEDULE_STATUS_NEEDS_ATTENTION,
    SCHEDULE_STATUS_SCHEDULED,
    ScheduleValidationError,
    TOOL_STATUS_BLOCKED,
    TOOL_STATUS_CANCELLED,
    TOOL_STATUS_CREATED,
    TOOL_STATUS_DELETED,
    TOOL_STATUS_DISABLED,
    TOOL_STATUS_ENABLED,
    TOOL_STATUS_ERROR,
    TOOL_STATUS_LISTED,
    TOOL_STATUS_NEEDS_CLARIFICATION,
    TOOL_STATUS_NEEDS_CONFIRMATION,
    TOOL_STATUS_UPDATED,
    VALID_MISS_POLICIES,
)


_RECORD_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_numeric_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "").strip())
    return text.replace("：", ":").replace("﹕", ":").replace("∶", ":")


def _contains_deferred_external_task(*values: Any) -> bool:
    combined = " ".join(_clean_text(value) for value in values).lower()
    deferred_needles = (
        "browser",
        "website",
        "web site",
        "camera",
        "payment",
        "login",
        "account",
        "system setting",
        "delete file",
        "modify file",
        "run command",
        "shell",
        "powershell",
        "外部",
        "網站",
        "網頁",
        "瀏覽器",
        "相機",
        "付款",
        "支付",
        "登入",
        "帳號",
        "系統設定",
        "刪除檔案",
        "修改檔案",
        "執行指令",
    )
    return any(needle in combined for needle in deferred_needles)


class _StateFileLock:
    def __init__(self, path: Path):
        self.path = path
        self._handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "a+b")
        if self._handle.seek(0, os.SEEK_END) == 0:
            self._handle.write(b"0")
            self._handle.flush()
        if os.name == "nt":
            import msvcrt

            self._handle.seek(0)
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_LOCK, 1)
        else:  # pragma: no cover - CI for this repo is normally Windows.
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


class ScheduleManager:
    """Owns all durable schedule, run, draft, and report state."""

    def __init__(
        self,
        app_dir: str | os.PathLike[str],
        *,
        state_dir: str | os.PathLike[str] = "schedule_state",
        claim_timeout_seconds: float = DEFAULT_CLAIM_TIMEOUT_SECONDS,
        draft_ttl_seconds: float = DEFAULT_DRAFT_TTL_SECONDS,
        undo_seconds: float = DEFAULT_UNDO_SECONDS,
        allow_interval: bool = False,
        miss_grace_seconds: float = 5.0,
        now_func=None,
    ):
        self.app_dir = Path(app_dir).resolve()
        state_path = Path(state_dir)
        if not state_path.is_absolute():
            state_path = self.app_dir / state_path
        self.state_dir = state_path.resolve()
        self.drafts_dir = self.state_dir / "drafts"
        self.schedules_dir = self.state_dir / "schedules"
        self.runs_dir = self.state_dir / "runs"
        self.pending_reports_dir = self.state_dir / "reports" / "pending"
        self.delivered_reports_dir = self.state_dir / "reports" / "delivered"
        self._lock_path = self.state_dir / ".schedule.lock"
        self.claim_timeout_seconds = max(1.0, float(claim_timeout_seconds))
        self.draft_ttl_seconds = max(60.0, float(draft_ttl_seconds))
        self.undo_seconds = max(15.0, float(undo_seconds))
        self.allow_interval = bool(allow_interval)
        self.miss_grace_seconds = max(0.0, float(miss_grace_seconds))
        self._now_func = now_func
        self.ensure_directories()

    def ensure_directories(self) -> None:
        for path in (
            self.drafts_dir,
            self.schedules_dir,
            self.runs_dir,
            self.pending_reports_dir,
            self.delivered_reports_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        with _StateFileLock(self._lock_path):
            yield

    def now(self) -> datetime:
        if self._now_func is not None:
            value = self._now_func()
            if value.tzinfo is None:
                return value.replace(tzinfo=self._get_timezone(DEFAULT_TIMEZONE))
            return value
        return datetime.now(self._get_timezone(DEFAULT_TIMEZONE))

    @staticmethod
    def _get_timezone(name: str | None):
        tz_name = _clean_text(name) or DEFAULT_TIMEZONE
        if ZoneInfo is not None:
            try:
                return ZoneInfo(tz_name)
            except Exception:
                pass
        if tz_name == DEFAULT_TIMEZONE:
            return timezone(timedelta(hours=8), DEFAULT_TIMEZONE)
        raise ScheduleValidationError(
            f"Invalid timezone: {tz_name}",
            field="trigger.timezone",
            user_message="這個時區無法辨識，請改用像 Asia/Taipei 這樣的時區名稱。",
        )

    @staticmethod
    def normalize_time_text(value: Any) -> str:
        text = _normalize_numeric_text(value)
        if not text:
            raise ScheduleValidationError(
                "Missing time.",
                field="trigger.time",
                user_message="請提供排程時間。",
            )
        parts = text.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ScheduleValidationError(
                f"Invalid time: {value}",
                field="trigger.time",
                user_message="時間格式需要像 08:05 或 20:00。",
            )
        hour, minute = int(parts[0]), int(parts[1])
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ScheduleValidationError(
                f"Impossible time: {value}",
                field="trigger.time",
                user_message="這個時間不存在，請輸入 00:00 到 23:59 之間的時間。",
            )
        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def _parse_date(value: Any) -> date:
        text = _normalize_numeric_text(value)
        try:
            return date.fromisoformat(text)
        except Exception as exc:
            raise ScheduleValidationError(
                f"Invalid date: {value}",
                field="trigger.date",
                user_message="日期格式需要像 2026-06-21，且必須是真實存在的日期。",
            ) from exc

    def _parse_datetime(self, value: Any, tz_name: str | None) -> datetime:
        text = _normalize_numeric_text(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except Exception as exc:
            raise ScheduleValidationError(
                f"Invalid datetime: {value}",
                field="trigger.run_at",
                user_message="日期時間格式無法辨識，請提供明確的未來日期與時間。",
            ) from exc
        tz = self._get_timezone(tz_name)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)

    @staticmethod
    def _time_from_text(value: str) -> dt_time:
        hour_text, minute_text = value.split(":", 1)
        return dt_time(hour=int(hour_text), minute=int(minute_text))

    def _canonical_trigger(
        self,
        trigger: dict[str, Any],
        *,
        require_future_once: bool,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(trigger, dict):
            raise ScheduleValidationError(
                "Missing trigger.",
                field="trigger",
                user_message="請提供排程時間。",
            )
        trigger_type = _clean_text(trigger.get("type")).lower()
        tz_name = _clean_text(trigger.get("timezone")) or DEFAULT_TIMEZONE
        tz = self._get_timezone(tz_name)
        current = (now or self.now()).astimezone(tz)

        if trigger_type == "once":
            if trigger.get("run_at"):
                run_at = self._parse_datetime(trigger.get("run_at"), tz_name)
            else:
                run_date = self._parse_date(trigger.get("date"))
                run_time = self._time_from_text(self.normalize_time_text(trigger.get("time")))
                run_at = datetime.combine(run_date, run_time, tzinfo=tz)
            if require_future_once and run_at <= current:
                raise ScheduleValidationError(
                    "One-time schedule is in the past.",
                    field="trigger.run_at",
                    user_message="一次性排程必須是未來時間，請重新設定。",
                )
            return {
                "type": "once",
                "run_at": run_at.isoformat(),
                "timezone": tz_name,
            }

        if trigger_type == "daily":
            return {
                "type": "daily",
                "time": self.normalize_time_text(trigger.get("time")),
                "timezone": tz_name,
            }

        if trigger_type == "weekly":
            raw_weekdays = trigger.get("weekdays", trigger.get("weekday"))
            if raw_weekdays is None:
                raise ScheduleValidationError(
                    "Missing weekdays.",
                    field="trigger.weekdays",
                    user_message="每週排程需要指定星期幾。",
                )
            if not isinstance(raw_weekdays, list):
                raw_weekdays = [raw_weekdays]
            weekdays: list[int] = []
            for raw_day in raw_weekdays:
                try:
                    day = int(raw_day)
                except (TypeError, ValueError) as exc:
                    raise ScheduleValidationError(
                        f"Invalid weekday: {raw_day}",
                        field="trigger.weekdays",
                        user_message="星期設定需要是 0 到 6，0 代表星期一。",
                    ) from exc
                if day < 0 or day > 6:
                    raise ScheduleValidationError(
                        f"Invalid weekday: {raw_day}",
                        field="trigger.weekdays",
                        user_message="星期設定需要是 0 到 6，0 代表星期一。",
                    )
                if day not in weekdays:
                    weekdays.append(day)
            return {
                "type": "weekly",
                "time": self.normalize_time_text(trigger.get("time")),
                "weekdays": sorted(weekdays),
                "timezone": tz_name,
            }

        if trigger_type == "interval":
            if not self.allow_interval:
                raise ScheduleValidationError(
                    "Interval schedules are disabled.",
                    field="trigger.type",
                    user_message="目前版本尚未開放間隔型排程，請改用一次、每天或每週。",
                )
            return deepcopy(trigger)

        raise ScheduleValidationError(
            f"Unsupported trigger type: {trigger_type}",
            field="trigger.type",
            user_message="目前支援一次、每天或每週排程。",
        )

    def _canonical_report(self, report: dict[str, Any] | None) -> dict[str, Any]:
        report = report if isinstance(report, dict) else {}
        required = bool(report.get("required", False))
        recipient = _clean_text(report.get("recipient"))
        sensitive = bool(report.get("sensitive", False))
        keep_latest_report_only = bool(report.get("keep_latest_report_only", False))
        if required and not recipient:
            raise ScheduleValidationError(
                "Missing report recipient.",
                field="report.recipient",
                user_message="需要報告時，也要指定報告收件人。",
            )
        return {
            "required": required,
            "recipient": recipient or None,
            "sensitive": sensitive,
            "keep_latest_report_only": keep_latest_report_only,
        }

    def _canonical_schedule_input(
        self,
        data: dict[str, Any],
        *,
        require_future_once: bool,
    ) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ScheduleValidationError(
                "Schedule payload must be an object.",
                user_message="排程資料格式不正確。",
            )
        title = _clean_text(data.get("title"))
        task_prompt = _clean_text(data.get("task_prompt") or data.get("prompt"))
        if not title:
            raise ScheduleValidationError(
                "Missing title.",
                field="title",
                user_message="請提供排程標題。",
            )
        if not task_prompt:
            raise ScheduleValidationError(
                "Missing task prompt.",
                field="task_prompt",
                user_message="請提供排程要做的內容。",
            )
        if _contains_deferred_external_task(title, task_prompt):
            raise ScheduleValidationError(
                "Deferred external/tool task.",
                field="task_prompt",
                user_message="目前版本只支援提醒與 LLM 摘要型排程；網站、系統、相機、帳號或外部工具任務尚未開放。",
            )
        now = self.now()
        trigger = self._canonical_trigger(
            data.get("trigger") or {},
            require_future_once=require_future_once,
            now=now,
        )
        report = self._canonical_report(data.get("report"))
        miss_policy = _clean_text(data.get("miss_policy")) or (
            "run_late" if trigger["type"] == "once" else "defer_until_idle"
        )
        if miss_policy not in VALID_MISS_POLICIES:
            raise ScheduleValidationError(
                f"Invalid miss policy: {miss_policy}",
                field="miss_policy",
                user_message="補跑策略只能是 skip、run_late 或 defer_until_idle。",
            )
        return {
            "title": title,
            "task_prompt": task_prompt,
            "trigger": trigger,
            "report": report,
            "miss_policy": miss_policy,
            "timezone": trigger.get("timezone", DEFAULT_TIMEZONE),
            "created_by": _clean_text(data.get("created_by")) or None,
            "source": _clean_text(data.get("source")) or "ui",
            "reminder_for": _clean_text(data.get("reminder_for")) or None,
            "enabled": bool(data.get("enabled", True)),
        }

    def _compute_next_run_at(
        self,
        trigger: dict[str, Any],
        *,
        after: datetime | None = None,
    ) -> str | None:
        current = after or self.now()
        tz = self._get_timezone(trigger.get("timezone") or DEFAULT_TIMEZONE)
        current = current.astimezone(tz)
        trigger_type = trigger.get("type")

        if trigger_type == "once":
            run_at = self._parse_datetime(trigger.get("run_at"), trigger.get("timezone"))
            return run_at.isoformat() if run_at > current else None

        if trigger_type == "daily":
            target_time = self._time_from_text(trigger["time"])
            candidate = datetime.combine(current.date(), target_time, tzinfo=tz)
            if candidate <= current:
                candidate += timedelta(days=1)
            return candidate.isoformat()

        if trigger_type == "weekly":
            target_time = self._time_from_text(trigger["time"])
            weekdays = list(trigger.get("weekdays") or [])
            candidates = []
            for day in weekdays:
                days_ahead = (int(day) - current.weekday()) % 7
                candidate_date = current.date() + timedelta(days=days_ahead)
                candidate = datetime.combine(candidate_date, target_time, tzinfo=tz)
                if candidate <= current:
                    candidate += timedelta(days=7)
                candidates.append(candidate)
            if not candidates:
                return None
            return min(candidates).isoformat()

        return None

    @staticmethod
    def _record_path(directory: Path, record_id: str, *, prefix: str) -> Path:
        normalized_id = str(record_id or "").strip()
        if (
            not _RECORD_ID_RE.fullmatch(normalized_id)
            or not normalized_id.startswith(f"{prefix}_")
        ):
            raise ScheduleValidationError(
                f"Invalid {prefix} id.",
                field=f"{prefix}_id",
                user_message="排程識別碼格式不正確。",
            )

        root = directory.resolve()
        candidate = (root / f"{normalized_id}.json").resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:  # pragma: no cover - guarded by the ID format check.
            raise ScheduleValidationError(
                f"Invalid {prefix} path.",
                field=f"{prefix}_id",
                user_message="排程識別碼格式不正確。",
            ) from exc
        return candidate

    def _schedule_path(self, schedule_id: str) -> Path:
        return self._record_path(self.schedules_dir, schedule_id, prefix="sched")

    def _draft_path(self, draft_id: str) -> Path:
        return self._record_path(self.drafts_dir, draft_id, prefix="draft")

    def _pending_report_path(self, report_id: str) -> Path:
        return self._record_path(self.pending_reports_dir, report_id, prefix="report")

    def _delivered_report_path(self, report_id: str) -> Path:
        return self._record_path(self.delivered_reports_dir, report_id, prefix="report")

    def _run_at_sort_key(self, value: Any, timezone_name: str | None = None) -> datetime:
        if not value:
            return datetime.max.replace(tzinfo=timezone.utc)
        try:
            return self._parse_datetime(value, timezone_name).astimezone(timezone.utc)
        except (ScheduleValidationError, TypeError, ValueError):
            return datetime.max.replace(tzinfo=timezone.utc)

    def _new_id(self, prefix: str, now: datetime | None = None) -> str:
        stamp = (now or self.now()).strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{stamp}_{uuid.uuid4().hex[:6]}"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)

    def _iter_json_objects(self, directory: Path) -> Iterator[dict[str, Any]]:
        if not directory.exists():
            return
        for path in sorted(directory.glob("*.json")):
            try:
                yield self._read_json(path)
            except Exception:
                continue

    def _result(
        self,
        status: str,
        *,
        operation: str,
        message_for_user: str | None = None,
        schedule_id: str | None = None,
        draft_id: str | None = None,
        operation_id: str | None = None,
        confirmation_question: str | None = None,
        clarification_question: str | None = None,
        undo_until: str | None = None,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
        **extra,
    ) -> dict[str, Any]:
        result = {
            "status": status,
            "operation": operation,
            "operation_id": operation_id,
            "draft_id": draft_id,
            "schedule_id": schedule_id,
            "message_for_user": message_for_user,
            "confirmation_question": confirmation_question,
            "clarification_question": clarification_question,
            "undo_until": undo_until,
            "errors": errors or [],
            "warnings": warnings or [],
        }
        result.update(extra)
        return result

    def _validation_result(self, exc: ScheduleValidationError, *, operation: str) -> dict[str, Any]:
        return self._result(
            TOOL_STATUS_NEEDS_CLARIFICATION,
            operation=operation,
            clarification_question=exc.user_message,
            errors=[str(exc)],
            field=exc.field,
        )

    def _is_low_risk_self_reminder(self, payload: dict[str, Any], draft: dict[str, Any]) -> bool:
        report = self._canonical_report(draft.get("report"))
        if report["required"] or report["sensitive"]:
            return False
        created_by = _clean_text(payload.get("created_by") or draft.get("created_by"))
        reminder_for = _clean_text(draft.get("reminder_for") or created_by)
        if not created_by:
            return False
        if reminder_for and reminder_for.lower() != created_by.lower():
            return False
        permission = draft.get("permission") if isinstance(draft.get("permission"), dict) else {}
        permission_mode = _clean_text(permission.get("mode")).lower()
        if permission_mode in {"requires_confirmation", "parent_only", "parent_confirmed"}:
            return False
        combined = " ".join(
            [
                _clean_text(payload.get("original_text")),
                _clean_text(draft.get("title")),
                _clean_text(draft.get("task_prompt")),
            ]
        ).lower()
        risky_needles = (
            "report",
            "monitor",
            "judge",
            "browser",
            "website",
            "camera",
            "payment",
            "login",
            "delete file",
            "modify file",
            "外部",
            "報告",
            "監督",
            "評分",
            "相機",
            "付款",
            "登入",
            "刪除檔案",
        )
        return not any(needle in combined for needle in risky_needles)

    def create_schedule(
        self,
        schedule_data: dict[str, Any],
        *,
        source: str = "ui",
        allow_undo: bool = False,
        require_future_once: bool = True,
    ) -> dict[str, Any]:
        try:
            canonical = self._canonical_schedule_input(
                schedule_data,
                require_future_once=require_future_once,
            )
        except ScheduleValidationError as exc:
            return self._validation_result(exc, operation="create")

        with self._locked():
            return self._create_schedule_record(
                canonical,
                source=source,
                allow_undo=allow_undo,
                operation="create",
            )

    def _create_schedule_record(
        self,
        canonical: dict[str, Any],
        *,
        source: str,
        allow_undo: bool,
        operation: str,
    ) -> dict[str, Any]:
        now = self.now()
        schedule_id = self._new_id("sched", now)
        operation_id = self._new_id("op", now) if allow_undo else None
        undo_until = (now + timedelta(seconds=self.undo_seconds)).isoformat() if allow_undo else None
        next_run_at = self._compute_next_run_at(canonical["trigger"], after=now)
        schedule = {
            "schema_version": SCHEMA_VERSION,
            "schedule_id": schedule_id,
            "title": canonical["title"],
            "task_prompt": canonical["task_prompt"],
            "created_by": canonical.get("created_by"),
            "source": source or canonical.get("source") or "ui",
            "reminder_for": canonical.get("reminder_for"),
            "enabled": canonical["enabled"],
            "trigger": canonical["trigger"],
            "report": canonical["report"],
            "miss_policy": canonical["miss_policy"],
            "status": SCHEDULE_STATUS_SCHEDULED if canonical["enabled"] else SCHEDULE_STATUS_DISABLED,
            "last_status": None,
            "next_run_at": next_run_at,
            "claimed_at": None,
            "claim_id": None,
            "consecutive_failures": 0,
            "pending_report_count": 0,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "last_run_at": None,
            "revision": 1,
            "change_history": [],
            "undo": {
                "operation_id": operation_id,
                "undo_until": undo_until,
            }
            if allow_undo
            else None,
        }
        self._atomic_write_json(self._schedule_path(schedule_id), schedule)
        return self._result(
            TOOL_STATUS_CREATED,
            operation=operation,
            schedule_id=schedule_id,
            operation_id=operation_id,
            undo_until=undo_until,
            message_for_user=f"已建立排程：{canonical['title']}。",
        )

    def draft_create(self, payload: dict[str, Any]) -> dict[str, Any]:
        draft_data = payload.get("draft") if isinstance(payload, dict) else None
        if not isinstance(draft_data, dict):
            return self._result(
                TOOL_STATUS_NEEDS_CLARIFICATION,
                operation="draft_create",
                clarification_question="請提供排程內容、時間和要做的事。",
                errors=["Missing draft object."],
            )
        draft_data = deepcopy(draft_data)
        draft_data["created_by"] = draft_data.get("created_by") or payload.get("created_by")
        draft_data["source"] = draft_data.get("source") or payload.get("source") or "conversation"

        try:
            self._canonical_schedule_input(draft_data, require_future_once=True)
        except ScheduleValidationError as exc:
            return self._validation_result(exc, operation="draft_create")

        if self._is_low_risk_self_reminder(payload, draft_data):
            return self.create_schedule(
                draft_data,
                source="conversation",
                allow_undo=True,
                require_future_once=True,
            )

        now = self.now()
        draft_id = self._new_id("draft", now)
        expires_at = now + timedelta(seconds=self.draft_ttl_seconds)
        draft = {
            "schema_version": SCHEMA_VERSION,
            "draft_id": draft_id,
            "status": "pending",
            "operation": payload.get("operation") or "create",
            "source": payload.get("source") or "conversation",
            "created_by": payload.get("created_by"),
            "original_text": payload.get("original_text"),
            "draft": draft_data,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "schedule_id": None,
        }
        with self._locked():
            self._atomic_write_json(self._draft_path(draft_id), draft)
        title = _clean_text(draft_data.get("title")) or "這個排程"
        question = f"請確認是否要建立排程「{title}」。確認後我才會啟用。"
        return self._result(
            TOOL_STATUS_NEEDS_CONFIRMATION,
            operation="draft_create",
            draft_id=draft_id,
            confirmation_question=question,
            draft_expires_at=expires_at.isoformat(),
        )

    def _load_pending_draft(self, draft_id: str) -> dict[str, Any]:
        path = self._draft_path(draft_id)
        if not path.exists():
            raise ScheduleValidationError(
                "Draft not found.",
                user_message="找不到這個待確認排程，請重新說明一次。",
            )
        draft = self._read_json(path)
        if draft.get("status") != "pending":
            raise ScheduleValidationError(
                "Draft is not pending.",
                user_message="這個待確認排程已經處理過了。",
            )
        expires_at = self._parse_datetime(draft.get("expires_at"), DEFAULT_TIMEZONE)
        if expires_at <= self.now().astimezone(expires_at.tzinfo):
            draft["status"] = "expired"
            draft["updated_at"] = self.now().isoformat()
            self._atomic_write_json(path, draft)
            raise ScheduleValidationError(
                "Draft expired.",
                user_message="前一個待確認排程已經過期，請重新說明一次。",
            )
        return draft

    def draft_confirm(self, draft_id: str) -> dict[str, Any]:
        with self._locked():
            try:
                draft = self._load_pending_draft(draft_id)
            except ScheduleValidationError as exc:
                return self._validation_result(exc, operation="draft_confirm")
            try:
                canonical = self._canonical_schedule_input(
                    draft["draft"],
                    require_future_once=True,
                )
            except ScheduleValidationError as exc:
                return self._validation_result(exc, operation="draft_confirm")
            result = self._create_schedule_record(
                canonical,
                source=draft.get("source") or "conversation",
                allow_undo=False,
                operation="draft_confirm",
            )
            if result["status"] != TOOL_STATUS_CREATED:
                return result
            draft["status"] = "confirmed"
            draft["schedule_id"] = result["schedule_id"]
            draft["updated_at"] = self.now().isoformat()
            self._atomic_write_json(self._draft_path(draft_id), draft)
            result["draft_id"] = draft_id
            return result

    def draft_cancel(self, draft_id: str) -> dict[str, Any]:
        with self._locked():
            try:
                path = self._draft_path(draft_id)
            except ScheduleValidationError as exc:
                return self._validation_result(exc, operation="draft_cancel")
            if not path.exists():
                return self._result(
                    TOOL_STATUS_CANCELLED,
                    operation="draft_cancel",
                    draft_id=draft_id,
                    message_for_user="沒有建立或更動任何排程。",
                )
            draft = self._read_json(path)
            draft["status"] = "cancelled"
            draft["updated_at"] = self.now().isoformat()
            self._atomic_write_json(path, draft)
        return self._result(
            TOOL_STATUS_CANCELLED,
            operation="draft_cancel",
            draft_id=draft_id,
            message_for_user="已取消，沒有建立排程。",
        )

    def draft_update(self, draft_id: str, patch_data: dict[str, Any]) -> dict[str, Any]:
        with self._locked():
            try:
                draft = self._load_pending_draft(draft_id)
            except ScheduleValidationError as exc:
                return self._validation_result(exc, operation="draft_update")
            updated = deepcopy(draft.get("draft") or {})
            updated.update(patch_data.get("draft") if "draft" in patch_data else patch_data)
            try:
                self._canonical_schedule_input(updated, require_future_once=True)
            except ScheduleValidationError as exc:
                return self._validation_result(exc, operation="draft_update")
            draft["draft"] = updated
            draft["updated_at"] = self.now().isoformat()
            self._atomic_write_json(self._draft_path(draft_id), draft)
        return self._result(
            TOOL_STATUS_NEEDS_CONFIRMATION,
            operation="draft_update",
            draft_id=draft_id,
            confirmation_question=f"已更新草稿。請確認是否要建立排程「{_clean_text(updated.get('title'))}」。",
            draft_expires_at=draft.get("expires_at"),
        )

    def list_schedules(self) -> dict[str, Any]:
        records = list(self._iter_json_objects(self.schedules_dir))
        records.sort(
            key=lambda item: self._run_at_sort_key(
                item.get("next_run_at"),
                item.get("timezone"),
            )
        )
        pending_counts: dict[str, int] = {}
        for report in self._iter_pending_reports():
            schedule_id = report.get("schedule_id")
            if schedule_id:
                pending_counts[schedule_id] = pending_counts.get(schedule_id, 0) + 1
        schedules = [
            self._schedule_summary(
                item,
                pending_report_count=pending_counts.get(item.get("schedule_id"), 0),
            )
            for item in records
        ]
        return self._result(
            TOOL_STATUS_LISTED,
            operation="list",
            schedules=schedules,
            message_for_user=f"目前有 {len(schedules)} 個排程。",
        )

    def _schedule_summary(
        self,
        schedule: dict[str, Any],
        *,
        pending_report_count: int | None = None,
    ) -> dict[str, Any]:
        if pending_report_count is None:
            pending_report_count = self.count_pending_reports(schedule.get("schedule_id"))
        return {
            "schedule_id": schedule.get("schedule_id"),
            "title": schedule.get("title"),
            "enabled": bool(schedule.get("enabled")),
            "trigger": schedule.get("trigger"),
            "next_run_at": schedule.get("next_run_at"),
            "status": schedule.get("status"),
            "last_status": schedule.get("last_status"),
            "report": schedule.get("report"),
            "pending_report_count": int(pending_report_count),
        }

    def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        try:
            path = self._schedule_path(schedule_id)
        except ScheduleValidationError:
            return None
        if not path.exists():
            return None
        return self._read_json(path)

    def _claim_is_active(self, schedule: dict[str, Any], now: datetime | None = None) -> bool:
        if not schedule.get("claim_id") or not schedule.get("claimed_at"):
            return False
        current = now or self.now()
        claimed_at = self._parse_datetime(schedule.get("claimed_at"), DEFAULT_TIMEZONE)
        return (current - claimed_at).total_seconds() <= self.claim_timeout_seconds

    def _release_stale_claim(self, schedule: dict[str, Any], now: datetime) -> bool:
        if not schedule.get("claim_id") or self._claim_is_active(schedule, now):
            return False
        schedule["claim_id"] = None
        schedule["claimed_at"] = None
        schedule["status"] = SCHEDULE_STATUS_DELAYED
        schedule["last_status"] = "stale_claim_released"
        schedule["updated_at"] = now.isoformat()
        return True

    def _record_missed_occurrence(
        self,
        schedule: dict[str, Any],
        *,
        scheduled_for: datetime,
        now: datetime,
    ) -> None:
        run_id = self._new_id("run", now)
        run_record = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "schedule_id": schedule.get("schedule_id"),
            "claim_id": None,
            "started_at": scheduled_for.isoformat(),
            "ended_at": now.isoformat(),
            "status": RUN_STATUS_MISSED,
            "error_type": "miss_policy_skip",
            "error_message": "Scheduled occurrence was skipped because it was already late.",
            "llm_request_id": None,
            "response_excerpt": "",
            "report_id": None,
        }
        run_dir = self.runs_dir / schedule["schedule_id"]
        self._atomic_write_json(run_dir / f"{run_id}.json", run_record)

        schedule["claim_id"] = None
        schedule["claimed_at"] = None
        schedule["last_run_at"] = now.isoformat()
        schedule["last_status"] = RUN_STATUS_MISSED
        schedule["updated_at"] = now.isoformat()
        if schedule.get("trigger", {}).get("type") == "once":
            schedule["enabled"] = False
            schedule["status"] = SCHEDULE_STATUS_MISSED
            schedule["next_run_at"] = None
        else:
            schedule["status"] = SCHEDULE_STATUS_SCHEDULED
            schedule["next_run_at"] = self._compute_next_run_at(schedule["trigger"], after=now)
        self._atomic_write_json(self._schedule_path(schedule["schedule_id"]), schedule)

    def claim_due_job(self, *, now: datetime | None = None) -> dict[str, Any] | None:
        current = now or self.now()
        with self._locked():
            for schedule in self._iter_json_objects(self.schedules_dir):
                changed = self._release_stale_claim(schedule, current)
                if changed:
                    self._atomic_write_json(self._schedule_path(schedule["schedule_id"]), schedule)

            candidates: list[dict[str, Any]] = []
            for schedule in self._iter_json_objects(self.schedules_dir):
                if not schedule.get("enabled", True):
                    continue
                if self._claim_is_active(schedule, current):
                    continue
                next_run_raw = schedule.get("next_run_at")
                if not next_run_raw:
                    continue
                next_run = self._parse_datetime(next_run_raw, schedule.get("timezone"))
                if next_run <= current.astimezone(next_run.tzinfo):
                    lateness_seconds = (
                        current.astimezone(next_run.tzinfo) - next_run
                    ).total_seconds()
                    if (
                        schedule.get("miss_policy") == "skip"
                        and lateness_seconds > self.miss_grace_seconds
                    ):
                        self._record_missed_occurrence(
                            schedule,
                            scheduled_for=next_run,
                            now=current,
                        )
                        continue
                    candidates.append(schedule)
            if not candidates:
                return None
            candidates.sort(
                key=lambda item: self._run_at_sort_key(
                    item.get("next_run_at"),
                    item.get("timezone"),
                )
            )
            schedule = candidates[0]
            claim_id = self._new_id("claim", current)
            schedule["claim_id"] = claim_id
            schedule["claimed_at"] = current.isoformat()
            schedule["status"] = SCHEDULE_STATUS_CLAIMED
            schedule["last_status"] = "claimed"
            schedule["updated_at"] = current.isoformat()
            self._atomic_write_json(self._schedule_path(schedule["schedule_id"]), schedule)
            return {
                "schedule_id": schedule["schedule_id"],
                "claim_id": claim_id,
                "claimed_at": current.isoformat(),
                "schedule": deepcopy(schedule),
            }

    def complete_claim(
        self,
        *,
        schedule_id: str,
        claim_id: str,
        status: str,
        response_text: str = "",
        llm_request_id: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        now = self.now()
        with self._locked():
            schedule = self.get_schedule(schedule_id)
            if schedule is None:
                return self._result(
                    TOOL_STATUS_ERROR,
                    operation="complete_claim",
                    errors=[f"Schedule not found: {schedule_id}"],
                )
            if schedule.get("claim_id") != claim_id:
                return self._result(
                    TOOL_STATUS_BLOCKED,
                    operation="complete_claim",
                    schedule_id=schedule_id,
                    errors=["Claim does not match current schedule state."],
                )
            run_id = self._new_id("run", now)
            report_id = None
            body = _clean_text(response_text)
            if status == RUN_STATUS_COMPLETED and schedule.get("report", {}).get("required") and body:
                report_id = self._write_pending_report(schedule, run_id, body, now)
            run_record = {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "schedule_id": schedule_id,
                "claim_id": claim_id,
                "started_at": schedule.get("claimed_at"),
                "ended_at": now.isoformat(),
                "status": status,
                "error_type": error_type,
                "error_message": error_message,
                "llm_request_id": llm_request_id,
                "response_excerpt": body[:240],
                "report_id": report_id,
            }
            run_dir = self.runs_dir / schedule_id
            self._atomic_write_json(run_dir / f"{run_id}.json", run_record)
            self._update_schedule_after_run(schedule, status, now)
            schedule["pending_report_count"] = self.count_pending_reports(schedule_id)
            self._atomic_write_json(self._schedule_path(schedule_id), schedule)
        return self._result(
            TOOL_STATUS_UPDATED,
            operation="complete_claim",
            schedule_id=schedule_id,
            run_id=run_id,
            report_id=report_id,
            message_for_user="排程執行紀錄已更新。",
        )

    def _write_pending_report(
        self,
        schedule: dict[str, Any],
        run_id: str,
        body: str,
        now: datetime,
    ) -> str:
        report_id = self._new_id("report", now)
        report = schedule.get("report") or {}
        record = {
            "schema_version": SCHEMA_VERSION,
            "report_id": report_id,
            "schedule_id": schedule.get("schedule_id"),
            "run_id": run_id,
            "title": schedule.get("title"),
            "recipient": report.get("recipient"),
            "sensitive": bool(report.get("sensitive")),
            "body": body,
            "status": "pending",
            "created_at": now.isoformat(),
            "attempt_count": 0,
            "last_prompted_at": None,
            "availability_prompt": {
                "awaiting": False,
                "report_ids": [],
                "requested_at": None,
                "requested_in_request_id": None,
            },
            "confirmation": {
                "required": bool(report.get("sensitive")),
                "awaiting": False,
                "requested_at": None,
                "requested_in_request_id": None,
            },
            "body_selected_in_request_id": None,
            "body_selected_at": None,
            "delivered_at": None,
            "delivered_in_request_id": None,
            "delivered_by": None,
        }
        self._atomic_write_json(self._pending_report_path(report_id), record)
        if bool(report.get("keep_latest_report_only")):
            self._delete_pending_reports_for_schedule(
                schedule.get("schedule_id"),
                keep_report_id=report_id,
            )
        return report_id

    def _delete_pending_reports_for_schedule(
        self,
        schedule_id: str | None,
        *,
        keep_report_id: str | None = None,
    ) -> int:
        if not schedule_id:
            return 0
        deleted = 0
        for report in self._iter_pending_reports():
            if report.get("schedule_id") != schedule_id:
                continue
            report_id = report.get("report_id")
            if keep_report_id and report_id == keep_report_id:
                continue
            if not report_id:
                continue
            try:
                report_path = self._pending_report_path(report_id)
            except ScheduleValidationError:
                continue
            report_path.unlink(missing_ok=True)
            deleted += 1
        return deleted

    def _update_schedule_after_run(
        self,
        schedule: dict[str, Any],
        status: str,
        now: datetime,
    ) -> None:
        schedule["claim_id"] = None
        schedule["claimed_at"] = None
        schedule["last_run_at"] = now.isoformat()
        schedule["last_status"] = status
        schedule["updated_at"] = now.isoformat()

        if status == RUN_STATUS_COMPLETED:
            schedule["consecutive_failures"] = 0
            if schedule.get("trigger", {}).get("type") == "once":
                schedule["enabled"] = False
                schedule["status"] = SCHEDULE_STATUS_COMPLETED
                schedule["next_run_at"] = None
                return
            schedule["status"] = SCHEDULE_STATUS_SCHEDULED
            schedule["next_run_at"] = self._compute_next_run_at(schedule["trigger"], after=now)
            return

        if status in {RUN_STATUS_FAILED, RUN_STATUS_INTERRUPTED}:
            schedule["consecutive_failures"] = int(schedule.get("consecutive_failures") or 0) + 1
            if schedule["consecutive_failures"] >= 3:
                schedule["enabled"] = False
                schedule["status"] = SCHEDULE_STATUS_NEEDS_ATTENTION
                schedule["next_run_at"] = None
            else:
                schedule["status"] = SCHEDULE_STATUS_DELAYED
                if schedule.get("trigger", {}).get("type") == "once":
                    schedule["next_run_at"] = (now + timedelta(minutes=5)).isoformat()
                else:
                    schedule["next_run_at"] = self._compute_next_run_at(schedule["trigger"], after=now)
            return

        schedule["status"] = status

    def _normalize_pending_report_record(self, report: dict[str, Any]) -> dict[str, Any]:
        normalized = deepcopy(report)
        normalized.setdefault("attempt_count", 0)
        normalized.setdefault("last_prompted_at", None)
        availability = normalized.get("availability_prompt")
        if not isinstance(availability, dict):
            availability = {}
        normalized["availability_prompt"] = {
            "awaiting": bool(availability.get("awaiting", False)),
            "report_ids": list(availability.get("report_ids") or []),
            "requested_at": availability.get("requested_at"),
            "requested_in_request_id": availability.get("requested_in_request_id"),
        }
        confirmation = normalized.get("confirmation")
        if not isinstance(confirmation, dict):
            confirmation = {}
        normalized["confirmation"] = {
            "required": bool(confirmation.get("required", normalized.get("sensitive", False))),
            "awaiting": bool(confirmation.get("awaiting", False)),
            "requested_at": confirmation.get("requested_at"),
            "requested_in_request_id": confirmation.get("requested_in_request_id"),
        }
        normalized.setdefault("body_selected_in_request_id", None)
        normalized.setdefault("body_selected_at", None)
        normalized.setdefault("delivered_at", None)
        normalized.setdefault("delivered_in_request_id", None)
        normalized.setdefault("delivered_by", None)
        return normalized

    def _iter_pending_reports(self) -> Iterator[dict[str, Any]]:
        reports = [self._normalize_pending_report_record(item) for item in self._iter_json_objects(self.pending_reports_dir)]
        reports.sort(key=lambda item: (item.get("created_at") or "", item.get("report_id") or ""))
        yield from reports

    def _update_schedule_pending_count(self, schedule_id: str | None) -> None:
        if not schedule_id:
            return
        schedule = self.get_schedule(schedule_id)
        if not schedule:
            return
        schedule["pending_report_count"] = self.count_pending_reports(schedule_id)
        schedule["updated_at"] = self.now().isoformat()
        self._atomic_write_json(self._schedule_path(schedule_id), schedule)

    def count_pending_reports(self, schedule_id: str | None = None) -> int:
        count = 0
        for report in self._iter_pending_reports():
            if schedule_id and report.get("schedule_id") != schedule_id:
                continue
            count += 1
        return count

    def list_pending_reports(
        self,
        *,
        recipient: str | None = None,
        include_body: bool = False,
    ) -> dict[str, Any]:
        recipient_clean = _clean_text(recipient).lower()
        reports = []
        for report in self._iter_pending_reports():
            if recipient_clean and _clean_text(report.get("recipient")).lower() != recipient_clean:
                continue
            item = {
                "report_id": report.get("report_id"),
                "schedule_id": report.get("schedule_id"),
                "title": report.get("title"),
                "recipient": report.get("recipient"),
                "sensitive": bool(report.get("sensitive")),
                "created_at": report.get("created_at"),
                "availability_prompt": report.get("availability_prompt"),
                "confirmation": report.get("confirmation"),
            }
            if include_body:
                item["body"] = report.get("body")
            reports.append(item)
        return self._result(
            TOOL_STATUS_LISTED,
            operation="reports_list",
            reports=reports,
            message_for_user=f"目前有 {len(reports)} 份待領取報告。",
        )

    def _matching_pending_reports(
        self,
        *,
        recipient: str | None = None,
        schedule_id: str | None = None,
    ) -> list[dict[str, Any]]:
        recipient_clean = _clean_text(recipient).lower()
        matched = []
        for report in self._iter_pending_reports():
            if recipient_clean and _clean_text(report.get("recipient")).lower() != recipient_clean:
                continue
            if schedule_id and report.get("schedule_id") != schedule_id:
                continue
            matched.append(report)
        return matched

    def has_awaiting_report_offer(self, recipient: str | None) -> bool:
        for report in self._matching_pending_reports(recipient=recipient):
            availability = report.get("availability_prompt") or {}
            if availability.get("awaiting"):
                return True
        return False

    def has_awaiting_sensitive_confirmation(self, recipient: str | None) -> bool:
        for report in self._matching_pending_reports(recipient=recipient):
            confirmation = report.get("confirmation") or {}
            if bool(report.get("sensitive")) and confirmation.get("awaiting"):
                return True
        return False

    def decline_pending_report_prompt(
        self,
        recipient: str | None,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        changed = 0
        with self._locked():
            for report in self._matching_pending_reports(recipient=recipient):
                availability = report.get("availability_prompt") or {}
                confirmation = report.get("confirmation") or {}
                if not availability.get("awaiting") and not confirmation.get("awaiting"):
                    continue
                availability["awaiting"] = False
                confirmation["awaiting"] = False
                report["availability_prompt"] = availability
                report["confirmation"] = confirmation
                report["last_prompted_at"] = self.now().isoformat()
                report["last_declined_in_request_id"] = request_id
                self._atomic_write_json(self._pending_report_path(report["report_id"]), report)
                changed += 1
        return self._result(
            TOOL_STATUS_UPDATED,
            operation="report_decline",
            message_for_user="已保留待領取報告，之後仍可再要求查看。",
            declined_count=changed,
        )

    def prepare_report_delivery_for_recipient(
        self,
        recipient: str | None,
        *,
        request_id: str | None = None,
        schedule_id: str | None = None,
        sensitive_confirmed: bool = False,
    ) -> dict[str, Any]:
        recipient_clean = _clean_text(recipient)
        if not recipient_clean:
            return self._result(
                TOOL_STATUS_BLOCKED,
                operation="report_prepare",
                message_for_user="目前無法確認報告收件人，因此不能交付報告內容。",
            )

        with self._locked():
            reports = self._matching_pending_reports(recipient=recipient_clean, schedule_id=schedule_id)
            if not reports:
                return self._result(
                    TOOL_STATUS_LISTED,
                    operation="report_prepare",
                    message_for_user=f"{recipient_clean} 目前沒有待領取排程報告。",
                    reports=[],
                )

            report = reports[0]
            report = self._normalize_pending_report_record(report)
            now = self.now()
            availability = report.get("availability_prompt") or {}
            confirmation = report.get("confirmation") or {}

            if bool(report.get("sensitive")) and not sensitive_confirmed:
                availability["awaiting"] = False
                confirmation["required"] = True
                confirmation["awaiting"] = True
                confirmation["requested_at"] = now.isoformat()
                confirmation["requested_in_request_id"] = request_id
                report["availability_prompt"] = availability
                report["confirmation"] = confirmation
                report["attempt_count"] = int(report.get("attempt_count") or 0) + 1
                report["last_prompted_at"] = now.isoformat()
                self._atomic_write_json(self._pending_report_path(report["report_id"]), report)
                return self._result(
                    TOOL_STATUS_NEEDS_CONFIRMATION,
                    operation="report_prepare",
                    report_id=report.get("report_id"),
                    message_for_user="這是一份敏感排程報告，請先確認是否現在要聽內容。",
                    confirmation_question="這是一份敏感排程報告。請確認現在是否要聽內容。",
                )

            availability["awaiting"] = False
            confirmation["awaiting"] = False
            report["availability_prompt"] = availability
            report["confirmation"] = confirmation
            report["body_selected_in_request_id"] = request_id
            report["body_selected_at"] = now.isoformat()
            report["attempt_count"] = int(report.get("attempt_count") or 0) + 1
            report["last_prompted_at"] = now.isoformat()
            self._atomic_write_json(self._pending_report_path(report["report_id"]), report)

        return self._result(
            TOOL_STATUS_UPDATED,
            operation="report_prepare",
            report_id=report.get("report_id"),
            message_for_user="已準備交付一份待領取報告。",
            reports=[
                {
                    "report_id": report.get("report_id"),
                    "schedule_id": report.get("schedule_id"),
                    "title": report.get("title"),
                    "recipient": report.get("recipient"),
                    "sensitive": bool(report.get("sensitive")),
                    "body": report.get("body"),
                }
            ],
        )

    def mark_report_delivered(
        self,
        report_id: str,
        *,
        delivered_by: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        with self._locked():
            try:
                path = self._pending_report_path(report_id)
            except ScheduleValidationError as exc:
                return self._validation_result(exc, operation="report_deliver")
            if not path.exists():
                return self._result(
                    TOOL_STATUS_BLOCKED,
                    operation="report_deliver",
                    errors=[f"Pending report not found: {report_id}"],
                    message_for_user="找不到這份待領取報告。",
                )
            report = self._normalize_pending_report_record(self._read_json(path))
            report["status"] = "delivered"
            report["delivered_at"] = self.now().isoformat()
            report["delivered_by"] = delivered_by
            report["delivered_in_request_id"] = request_id
            self._atomic_write_json(self._delivered_report_path(report_id), report)
            path.unlink(missing_ok=True)
            self._update_schedule_pending_count(report.get("schedule_id"))
        return self._result(
            TOOL_STATUS_UPDATED,
            operation="report_deliver",
            message_for_user="已標記報告為已交付。",
            report_id=report_id,
        )

    def delete_schedule(self, schedule_id: str) -> dict[str, Any]:
        with self._locked():
            schedule = self.get_schedule(schedule_id)
            if schedule is None:
                return self._result(
                    TOOL_STATUS_BLOCKED,
                    operation="delete",
                    schedule_id=schedule_id,
                    message_for_user="找不到這個排程。",
                )
            if self._claim_is_active(schedule):
                return self._result(
                    TOOL_STATUS_BLOCKED,
                    operation="delete",
                    schedule_id=schedule_id,
                    message_for_user="這個排程正在執行中，現在不能刪除。",
                )
            self._schedule_path(schedule_id).unlink(missing_ok=True)
        return self._result(
            TOOL_STATUS_DELETED,
            operation="delete",
            schedule_id=schedule_id,
            message_for_user=f"已刪除排程：{schedule.get('title')}",
        )

    def set_enabled(self, schedule_id: str, enabled: bool) -> dict[str, Any]:
        with self._locked():
            schedule = self.get_schedule(schedule_id)
            if schedule is None:
                return self._result(
                    TOOL_STATUS_BLOCKED,
                    operation="enable" if enabled else "disable",
                    schedule_id=schedule_id,
                    message_for_user="找不到這個排程。",
                )
            now = self.now()
            next_run_at = (
                self._compute_next_run_at(schedule["trigger"], after=now)
                if enabled
                else None
            )
            if enabled and not next_run_at:
                schedule["enabled"] = False
                schedule["status"] = SCHEDULE_STATUS_DISABLED
                schedule["next_run_at"] = None
                schedule["updated_at"] = now.isoformat()
                self._atomic_write_json(self._schedule_path(schedule_id), schedule)
                return self._result(
                    TOOL_STATUS_BLOCKED,
                    operation="enable",
                    schedule_id=schedule_id,
                    message_for_user="這個一次性排程的時間已經過了，請編輯成未來時間後再啟用。",
                )
            schedule["enabled"] = bool(enabled)
            schedule["status"] = SCHEDULE_STATUS_SCHEDULED if enabled else SCHEDULE_STATUS_DISABLED
            schedule["next_run_at"] = next_run_at
            schedule["updated_at"] = now.isoformat()
            self._atomic_write_json(self._schedule_path(schedule_id), schedule)
        return self._result(
            TOOL_STATUS_ENABLED if enabled else TOOL_STATUS_DISABLED,
            operation="enable" if enabled else "disable",
            schedule_id=schedule_id,
            message_for_user=f"已{'啟用' if enabled else '停用'}排程：{schedule.get('title')}",
        )

    def update_schedule(
        self,
        schedule_id: str,
        patch_data: dict[str, Any],
        *,
        source: str | None = None,
    ) -> dict[str, Any]:
        with self._locked():
            current = self.get_schedule(schedule_id)
            if current is None:
                return self._result(
                    TOOL_STATUS_BLOCKED,
                    operation="edit",
                    schedule_id=schedule_id,
                    message_for_user="找不到這個排程。",
                )
            if self._claim_is_active(current):
                return self._result(
                    TOOL_STATUS_BLOCKED,
                    operation="edit",
                    schedule_id=schedule_id,
                    message_for_user="這個排程正在執行中，現在不能編輯主要內容。",
                )
            previous_snapshot = {
                "title": current.get("title"),
                "task_prompt": current.get("task_prompt"),
                "trigger": deepcopy(current.get("trigger")),
                "report": deepcopy(current.get("report")),
                "miss_policy": current.get("miss_policy"),
                "enabled": current.get("enabled", True),
            }
            updated_input = {
                "title": current.get("title"),
                "task_prompt": current.get("task_prompt"),
                "trigger": current.get("trigger"),
                "report": current.get("report"),
                "miss_policy": current.get("miss_policy"),
                "created_by": current.get("created_by"),
                "source": current.get("source"),
                "reminder_for": current.get("reminder_for"),
                "enabled": current.get("enabled", True),
            }
            updated_input.update(patch_data)
            try:
                canonical = self._canonical_schedule_input(
                    updated_input,
                    require_future_once=bool(updated_input.get("enabled", True)),
                )
            except ScheduleValidationError as exc:
                return self._validation_result(exc, operation="edit")
            now = self.now()
            next_run_at = (
                self._compute_next_run_at(canonical["trigger"], after=now)
                if canonical["enabled"]
                else None
            )
            if canonical["enabled"] and not next_run_at:
                return self._result(
                    TOOL_STATUS_BLOCKED,
                    operation="edit",
                    schedule_id=schedule_id,
                    message_for_user="這個一次性排程的時間已經過了，請改成未來時間或保持停用。",
                )
            current.update(
                {
                    "title": canonical["title"],
                    "task_prompt": canonical["task_prompt"],
                    "trigger": canonical["trigger"],
                    "report": canonical["report"],
                    "miss_policy": canonical["miss_policy"],
                    "enabled": canonical["enabled"],
                    "status": SCHEDULE_STATUS_SCHEDULED
                    if canonical["enabled"]
                    else SCHEDULE_STATUS_DISABLED,
                    "next_run_at": next_run_at,
                    "updated_at": now.isoformat(),
                }
            )
            current_snapshot = {
                "title": current.get("title"),
                "task_prompt": current.get("task_prompt"),
                "trigger": deepcopy(current.get("trigger")),
                "report": deepcopy(current.get("report")),
                "miss_policy": current.get("miss_policy"),
                "enabled": current.get("enabled", True),
            }
            history = list(current.get("change_history") or [])
            history.append(
                {
                    "changed_at": now.isoformat(),
                    "operation": "edit",
                    "source": _clean_text(source) or "unknown",
                    "before": previous_snapshot,
                    "after": current_snapshot,
                }
            )
            current["change_history"] = history[-20:]
            current["revision"] = int(current.get("revision") or 1) + 1
            self._atomic_write_json(self._schedule_path(schedule_id), current)
        return self._result(
            TOOL_STATUS_UPDATED,
            operation="edit",
            schedule_id=schedule_id,
            message_for_user=f"已更新排程：{current.get('title')}",
        )

    def undo(self, operation_id: str) -> dict[str, Any]:
        operation_id = _clean_text(operation_id)
        if not operation_id:
            return self._result(
                TOOL_STATUS_BLOCKED,
                operation="undo",
                message_for_user="找不到可以復原的操作。",
            )
        with self._locked():
            for schedule in self._iter_json_objects(self.schedules_dir):
                undo = schedule.get("undo") if isinstance(schedule.get("undo"), dict) else {}
                if undo.get("operation_id") != operation_id:
                    continue
                undo_until = self._parse_datetime(undo.get("undo_until"), DEFAULT_TIMEZONE)
                if undo_until <= self.now().astimezone(undo_until.tzinfo):
                    return self._result(
                        TOOL_STATUS_BLOCKED,
                        operation="undo",
                        schedule_id=schedule.get("schedule_id"),
                        message_for_user="復原時間已過，這個排程仍然保留。",
                    )
                if self._claim_is_active(schedule):
                    return self._result(
                        TOOL_STATUS_BLOCKED,
                        operation="undo",
                        schedule_id=schedule.get("schedule_id"),
                        message_for_user="排程正在執行中，不能復原。",
                    )
                self._schedule_path(schedule["schedule_id"]).unlink(missing_ok=True)
                return self._result(
                    TOOL_STATUS_DELETED,
                    operation="undo",
                    schedule_id=schedule.get("schedule_id"),
                    message_for_user=f"已復原並移除排程：{schedule.get('title')}",
                )
        return self._result(
            TOOL_STATUS_BLOCKED,
            operation="undo",
            message_for_user="找不到可以復原的操作。",
        )

    def pending_report_notice_for_recipient(
        self,
        recipient: str | None,
        *,
        limit: int = 2,
        request_id: str | None = None,
    ) -> str | None:
        if not recipient:
            return None
        with self._locked():
            reports = self._matching_pending_reports(recipient=recipient)
            if reports:
                now = self.now()
                selected_ids = [report.get("report_id") for report in reports[: max(1, limit)] if report.get("report_id")]
                for report in reports[: max(1, limit)]:
                    report = self._normalize_pending_report_record(report)
                    availability = report.get("availability_prompt") or {}
                    availability["awaiting"] = True
                    availability["report_ids"] = selected_ids
                    availability["requested_at"] = now.isoformat()
                    availability["requested_in_request_id"] = request_id
                    report["availability_prompt"] = availability
                    report["attempt_count"] = int(report.get("attempt_count") or 0) + 1
                    report["last_prompted_at"] = now.isoformat()
                    self._atomic_write_json(self._pending_report_path(report["report_id"]), report)
        if not reports:
            return None
        titles = "、".join(_clean_text(item.get("title")) for item in reports[: max(1, limit)])
        return (
            f"{recipient} 目前有 {len(reports)} 份待領取排程報告"
            f"（{titles}）。只能先告知有報告；若使用者明確要求查看，再使用 schedule tool 處理。"
        )
