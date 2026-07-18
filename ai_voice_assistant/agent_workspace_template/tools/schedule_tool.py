from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _resolve_app_dir() -> Path:
    env_path = os.environ.get("AI_GOVERNESS_APP_DIR")
    if env_path:
        return Path(env_path).resolve()
    return Path(__file__).resolve().parents[2]


APP_DIR = _resolve_app_dir()
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.schedule_manager import ScheduleManager  # noqa: E402


def _safe_result(status: str, operation: str, message: str, *, errors=None):
    return {
        "status": status,
        "operation": operation,
        "operation_id": None,
        "draft_id": None,
        "schedule_id": None,
        "message_for_user": message,
        "confirmation_question": None,
        "clarification_question": message if status == "needs_clarification" else None,
        "undo_until": None,
        "errors": errors or [],
        "warnings": [],
    }


def _print_json(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _manager() -> ScheduleManager:
    state_dir = os.environ.get("AI_GOVERNESS_SCHEDULE_STATE_DIR", "schedule_state")
    claim_timeout = float(os.environ.get("AI_GOVERNESS_SCHEDULE_CLAIM_TIMEOUT", "600"))
    return ScheduleManager(
        APP_DIR,
        state_dir=state_dir,
        claim_timeout_seconds=claim_timeout,
    )


def _payload_root() -> Path:
    configured = os.environ.get("AI_GOVERNESS_TOOL_PAYLOAD_DIR")
    if configured:
        return Path(configured).resolve()
    return (APP_DIR / "agent_workspace" / "tool_payloads" / "schedule").resolve()


def _load_payload(path_text: str) -> dict:
    raw_path = Path(path_text)
    path = raw_path if raw_path.is_absolute() else (Path.cwd() / raw_path)
    path = path.resolve()
    root = _payload_root()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Payload must be under {root}") from exc
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Payload JSON must be an object.")
    return payload


def _payload_or_error(args, operation: str):
    try:
        return _load_payload(args.payload), None
    except Exception as exc:
        return None, _safe_result(
            "needs_clarification",
            operation,
            "排程工具讀不到有效的 payload，請重新產生工具輸入。",
            errors=[str(exc)],
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Governess schedule tool")
    subparsers = parser.add_subparsers(dest="action", required=True)

    create = subparsers.add_parser("draft-create")
    create.add_argument("--payload", required=True)

    confirm = subparsers.add_parser("draft-confirm")
    confirm.add_argument("--draft-id", required=True)

    cancel = subparsers.add_parser("draft-cancel")
    cancel.add_argument("--draft-id", required=True)

    update = subparsers.add_parser("draft-update")
    update.add_argument("--draft-id", required=True)
    update.add_argument("--payload", required=True)

    undo = subparsers.add_parser("undo")
    undo.add_argument("--operation-id", required=True)

    subparsers.add_parser("list")

    delete = subparsers.add_parser("delete")
    delete.add_argument("--schedule-id", required=True)

    enable = subparsers.add_parser("enable")
    enable.add_argument("--schedule-id", required=True)

    disable = subparsers.add_parser("disable")
    disable.add_argument("--schedule-id", required=True)

    edit = subparsers.add_parser("edit")
    edit.add_argument("--schedule-id", required=True)
    edit.add_argument("--payload", required=True)

    reports = subparsers.add_parser("reports-list")
    reports.add_argument("--recipient", default="")
    reports.add_argument("--include-body", action="store_true")

    deliver = subparsers.add_parser("report-deliver")
    deliver.add_argument("--report-id", required=True)
    deliver.add_argument("--delivered-by", default="")

    return parser


def run(argv: list[str] | None = None) -> dict:
    args = build_parser().parse_args(argv)
    manager = _manager()

    if args.action == "draft-create":
        payload, error = _payload_or_error(args, "draft_create")
        return error or manager.draft_create(payload)
    if args.action == "draft-confirm":
        return manager.draft_confirm(args.draft_id)
    if args.action == "draft-cancel":
        return manager.draft_cancel(args.draft_id)
    if args.action == "draft-update":
        payload, error = _payload_or_error(args, "draft_update")
        return error or manager.draft_update(args.draft_id, payload)
    if args.action == "undo":
        return manager.undo(args.operation_id)
    if args.action == "list":
        return manager.list_schedules()
    if args.action == "delete":
        return manager.delete_schedule(args.schedule_id)
    if args.action == "enable":
        return manager.set_enabled(args.schedule_id, True)
    if args.action == "disable":
        return manager.set_enabled(args.schedule_id, False)
    if args.action == "edit":
        payload, error = _payload_or_error(args, "edit")
        return error or manager.update_schedule(
            args.schedule_id,
            payload,
            source="conversation",
        )
    if args.action == "reports-list":
        if bool(args.include_body):
            return _safe_result(
                "blocked",
                "reports_list",
                "報告內容由 app 依收件人確認後交付，schedule tool 只列出待領取報告。",
            )
        return manager.list_pending_reports(
            recipient=args.recipient or None,
            include_body=False,
        )
    if args.action == "report-deliver":
        return _safe_result(
            "blocked",
            "report_deliver",
            "報告交付與 delivered 標記由 app 在成功交付內容後處理，schedule tool 不能直接標記。",
        )
    return _safe_result("error", args.action, "Unsupported schedule tool action.")


def main(argv: list[str] | None = None) -> int:
    try:
        _print_json(run(argv))
        return 0
    except Exception as exc:
        _print_json(
            _safe_result(
                "error",
                "schedule_tool",
                "排程工具發生錯誤，沒有建立或更動排程。",
                errors=[f"{type(exc).__name__}: {exc}"],
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
