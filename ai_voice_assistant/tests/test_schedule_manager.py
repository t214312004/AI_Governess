from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from core.schedule_manager import ScheduleManager


TAIPEI = timezone(timedelta(hours=8), "Asia/Taipei")


def make_manager(tmp_path, now):
    current = {"value": now}
    manager = ScheduleManager(tmp_path, now_func=lambda: current["value"])
    return manager, current


def reminder_payload(**overrides):
    payload = {
        "title": "Drink water",
        "task_prompt": "Remind PersonA to drink water.",
        "created_by": "PersonA",
        "trigger": {
            "type": "once",
            "date": "2026-06-21",
            "time": "20:00",
            "timezone": "Asia/Taipei",
        },
        "report": {"required": False},
    }
    payload.update(overrides)
    return payload


def test_schedule_manager_creates_state_dirs_and_schedule(tmp_path):
    manager, _current = make_manager(tmp_path, datetime(2026, 6, 21, 10, 0, tzinfo=TAIPEI))

    result = manager.create_schedule(reminder_payload())

    assert result["status"] == "created"
    assert (manager.state_dir / "schedules" / f"{result['schedule_id']}.json").exists()
    assert (manager.state_dir / "drafts").exists()
    assert (manager.state_dir / "reports" / "pending").exists()


def test_schedule_manager_rejects_impossible_time(tmp_path):
    manager, _current = make_manager(tmp_path, datetime(2026, 6, 21, 10, 0, tzinfo=TAIPEI))

    result = manager.create_schedule(
        reminder_payload(trigger={"type": "once", "date": "2026-06-21", "time": "25:99"})
    )

    assert result["status"] == "needs_clarification"
    assert result["field"] == "trigger.time"


def test_schedule_manager_rejects_default_interval_creation(tmp_path):
    manager, _current = make_manager(tmp_path, datetime(2026, 6, 21, 10, 0, tzinfo=TAIPEI))

    result = manager.create_schedule(
        reminder_payload(trigger={"type": "interval", "minutes": 30})
    )

    assert result["status"] == "needs_clarification"
    assert result["field"] == "trigger.type"


def test_schedule_manager_rejects_deferred_external_tool_tasks(tmp_path):
    manager, _current = make_manager(tmp_path, datetime(2026, 6, 21, 10, 0, tzinfo=TAIPEI))

    result = manager.create_schedule(
        reminder_payload(task_prompt="Open a website and login every night.")
    )

    assert result["status"] == "needs_clarification"
    assert result["field"] == "task_prompt"


def test_schedule_manager_computes_daily_and_weekly_next_run(tmp_path):
    manager, _current = make_manager(tmp_path, datetime(2026, 6, 21, 10, 0, tzinfo=TAIPEI))

    daily = manager.create_schedule(
        reminder_payload(trigger={"type": "daily", "time": "8:5", "timezone": "Asia/Taipei"})
    )
    weekly = manager.create_schedule(
        reminder_payload(
            title="Weekly",
            trigger={"type": "weekly", "time": "09:30", "weekdays": [6], "timezone": "Asia/Taipei"},
        )
    )

    daily_schedule = manager.get_schedule(daily["schedule_id"])
    weekly_schedule = manager.get_schedule(weekly["schedule_id"])
    assert "2026-06-22T08:05" in daily_schedule["next_run_at"]
    assert "2026-06-28T09:30" in weekly_schedule["next_run_at"]


def test_schedule_manager_claims_exactly_one_due_job_and_skips_disabled(tmp_path):
    manager, current = make_manager(tmp_path, datetime(2026, 6, 21, 8, 0, tzinfo=TAIPEI))
    due = manager.create_schedule(
        reminder_payload(trigger={"type": "daily", "time": "08:05", "timezone": "Asia/Taipei"})
    )
    disabled = manager.create_schedule(
        reminder_payload(
            title="Disabled",
            trigger={"type": "daily", "time": "08:05", "timezone": "Asia/Taipei"},
        )
    )
    manager.set_enabled(disabled["schedule_id"], False)
    current["value"] = datetime(2026, 6, 21, 8, 6, tzinfo=TAIPEI)

    claim = manager.claim_due_job()
    second_claim = manager.claim_due_job()

    assert claim["schedule_id"] == due["schedule_id"]
    assert second_claim is None


def test_schedule_manager_orders_due_jobs_by_absolute_time(tmp_path):
    manager, current = make_manager(tmp_path, datetime(2025, 12, 31, 10, 0, tzinfo=TAIPEI))
    early = manager.create_schedule(
        reminder_payload(
            title="Earlier absolute time",
            trigger={
                "type": "once",
                "date": "2026-01-01",
                "time": "09:30",
                "timezone": "Asia/Taipei",
            },
        )
    )
    manager.create_schedule(
        reminder_payload(
            title="Later absolute time",
            trigger={
                "type": "once",
                "date": "2026-01-01",
                "time": "02:00",
                "timezone": "UTC",
            },
        )
    )
    current["value"] = datetime(2026, 1, 1, 10, 30, tzinfo=TAIPEI)

    claim = manager.claim_due_job()

    assert claim["schedule_id"] == early["schedule_id"]


def test_schedule_manager_skip_policy_records_missed_run_and_advances(tmp_path):
    manager, current = make_manager(tmp_path, datetime(2026, 6, 21, 8, 0, tzinfo=TAIPEI))
    result = manager.create_schedule(
        reminder_payload(
            trigger={"type": "daily", "time": "08:05", "timezone": "Asia/Taipei"},
            miss_policy="skip",
        )
    )
    current["value"] = datetime(2026, 6, 21, 8, 6, tzinfo=TAIPEI)

    assert manager.claim_due_job() is None

    schedule = manager.get_schedule(result["schedule_id"])
    assert schedule["last_status"] == "missed"
    assert "2026-06-22T08:05" in schedule["next_run_at"]
    run_path = next((manager.runs_dir / result["schedule_id"]).glob("*.json"))
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert run["status"] == "missed"
    assert run["error_type"] == "miss_policy_skip"


def test_schedule_manager_run_late_policy_claims_overdue_job(tmp_path):
    manager, current = make_manager(tmp_path, datetime(2026, 6, 21, 8, 0, tzinfo=TAIPEI))
    result = manager.create_schedule(
        reminder_payload(
            trigger={"type": "daily", "time": "08:05", "timezone": "Asia/Taipei"},
            miss_policy="run_late",
        )
    )
    current["value"] = datetime(2026, 6, 21, 10, 0, tzinfo=TAIPEI)

    claim = manager.claim_due_job()

    assert claim["schedule_id"] == result["schedule_id"]


def test_schedule_manager_edit_appends_bounded_audit_entry_with_edit_source(tmp_path):
    manager, _current = make_manager(tmp_path, datetime(2026, 6, 21, 8, 0, tzinfo=TAIPEI))
    result = manager.create_schedule(
        reminder_payload(trigger={"type": "daily", "time": "09:00", "timezone": "Asia/Taipei"}),
        source="ui",
    )

    manager.update_schedule(
        result["schedule_id"],
        {"title": "Updated title"},
        source="conversation",
    )

    schedule = manager.get_schedule(result["schedule_id"])
    assert schedule["revision"] == 2
    assert schedule["change_history"][-1]["before"]["title"] == "Drink water"
    assert schedule["change_history"][-1]["after"]["title"] == "Updated title"
    assert schedule["change_history"][-1]["source"] == "conversation"


def test_schedule_manager_blocks_reenabling_past_once_schedule(tmp_path):
    manager, current = make_manager(tmp_path, datetime(2026, 6, 21, 8, 0, tzinfo=TAIPEI))
    result = manager.create_schedule(
        reminder_payload(trigger={"type": "once", "date": "2026-06-21", "time": "08:30"})
    )
    manager.set_enabled(result["schedule_id"], False)
    current["value"] = datetime(2026, 6, 21, 9, 0, tzinfo=TAIPEI)

    enabled = manager.set_enabled(result["schedule_id"], True)
    schedule = manager.get_schedule(result["schedule_id"])

    assert enabled["status"] == "blocked"
    assert schedule["enabled"] is False
    assert schedule["status"] == "disabled"
    assert schedule["next_run_at"] is None
    assert manager.claim_due_job() is None


def test_schedule_manager_rejects_enabled_edit_to_past_once_schedule(tmp_path):
    manager, _current = make_manager(tmp_path, datetime(2026, 6, 21, 9, 0, tzinfo=TAIPEI))
    result = manager.create_schedule(
        reminder_payload(trigger={"type": "daily", "time": "10:00", "timezone": "Asia/Taipei"})
    )

    edited = manager.update_schedule(
        result["schedule_id"],
        {"trigger": {"type": "once", "date": "2026-06-21", "time": "08:30"}},
    )
    schedule = manager.get_schedule(result["schedule_id"])

    assert edited["status"] in {"blocked", "needs_clarification"}
    assert schedule["trigger"]["type"] == "daily"
    assert schedule["enabled"] is True
    assert schedule["next_run_at"]


def test_schedule_manager_releases_stale_claim(tmp_path):
    manager, current = make_manager(tmp_path, datetime(2026, 6, 21, 8, 0, tzinfo=TAIPEI))
    manager.claim_timeout_seconds = 30
    result = manager.create_schedule(
        reminder_payload(trigger={"type": "daily", "time": "08:05", "timezone": "Asia/Taipei"})
    )
    current["value"] = datetime(2026, 6, 21, 8, 6, tzinfo=TAIPEI)
    first = manager.claim_due_job()
    assert first["schedule_id"] == result["schedule_id"]

    current["value"] = datetime(2026, 6, 21, 8, 7, tzinfo=TAIPEI)
    second = manager.claim_due_job()

    assert second["schedule_id"] == result["schedule_id"]
    assert second["claim_id"] != first["claim_id"]


def test_schedule_manager_completion_writes_pending_report_when_required(tmp_path):
    manager, current = make_manager(tmp_path, datetime(2026, 6, 21, 8, 0, tzinfo=TAIPEI))
    result = manager.create_schedule(
        reminder_payload(
            trigger={"type": "daily", "time": "08:05", "timezone": "Asia/Taipei"},
            report={"required": True, "recipient": "PersonA", "sensitive": False},
        )
    )
    current["value"] = datetime(2026, 6, 21, 8, 6, tzinfo=TAIPEI)
    claim = manager.claim_due_job()

    complete = manager.complete_claim(
        schedule_id=result["schedule_id"],
        claim_id=claim["claim_id"],
        status="completed",
        response_text="Report body",
        llm_request_id="hb-test",
    )

    assert complete["report_id"]
    reports = manager.list_pending_reports(recipient="PersonA", include_body=True)["reports"]
    assert reports[0]["body"] == "Report body"


def test_schedule_manager_keep_latest_report_prunes_older_pending_reports(tmp_path):
    manager, current = make_manager(tmp_path, datetime(2026, 6, 21, 8, 0, tzinfo=TAIPEI))
    result = manager.create_schedule(
        reminder_payload(
            trigger={"type": "daily", "time": "08:05", "timezone": "Asia/Taipei"},
            report={
                "required": True,
                "recipient": "PersonA",
                "sensitive": False,
                "keep_latest_report_only": True,
            },
        )
    )

    current["value"] = datetime(2026, 6, 21, 8, 6, tzinfo=TAIPEI)
    first_claim = manager.claim_due_job()
    first_complete = manager.complete_claim(
        schedule_id=result["schedule_id"],
        claim_id=first_claim["claim_id"],
        status="completed",
        response_text="Day one report",
        llm_request_id="hb-day-one",
    )

    current["value"] = datetime(2026, 6, 22, 8, 6, tzinfo=TAIPEI)
    second_claim = manager.claim_due_job()
    second_complete = manager.complete_claim(
        schedule_id=result["schedule_id"],
        claim_id=second_claim["claim_id"],
        status="completed",
        response_text="Day two report",
        llm_request_id="hb-day-two",
    )

    reports = manager.list_pending_reports(recipient="PersonA", include_body=True)["reports"]
    assert [report["report_id"] for report in reports] == [second_complete["report_id"]]
    assert reports[0]["body"] == "Day two report"
    assert not (manager.pending_reports_dir / f"{first_complete['report_id']}.json").exists()
    assert manager.count_pending_reports(result["schedule_id"]) == 1


def test_schedule_manager_notice_tracks_availability_without_body(tmp_path):
    manager, current = make_manager(tmp_path, datetime(2026, 6, 21, 8, 0, tzinfo=TAIPEI))
    result = manager.create_schedule(
        reminder_payload(
            trigger={"type": "daily", "time": "08:05", "timezone": "Asia/Taipei"},
            report={"required": True, "recipient": "PersonA", "sensitive": False},
        )
    )
    current["value"] = datetime(2026, 6, 21, 8, 6, tzinfo=TAIPEI)
    claim = manager.claim_due_job()
    manager.complete_claim(
        schedule_id=result["schedule_id"],
        claim_id=claim["claim_id"],
        status="completed",
        response_text="Private report body",
        llm_request_id="hb-test",
    )

    notice = manager.pending_report_notice_for_recipient("PersonA", request_id="req-offer")
    reports = manager.list_pending_reports(recipient="PersonA", include_body=False)["reports"]

    assert "Private report body" not in notice
    assert reports[0]["availability_prompt"]["awaiting"] is True
    assert reports[0]["availability_prompt"]["requested_in_request_id"] == "req-offer"
    assert "body" not in reports[0]


def test_schedule_manager_prepare_and_deliver_pending_report(tmp_path):
    manager, current = make_manager(tmp_path, datetime(2026, 6, 21, 8, 0, tzinfo=TAIPEI))
    result = manager.create_schedule(
        reminder_payload(
            trigger={"type": "daily", "time": "08:05", "timezone": "Asia/Taipei"},
            report={"required": True, "recipient": "PersonA", "sensitive": False},
        )
    )
    current["value"] = datetime(2026, 6, 21, 8, 6, tzinfo=TAIPEI)
    claim = manager.claim_due_job()
    complete = manager.complete_claim(
        schedule_id=result["schedule_id"],
        claim_id=claim["claim_id"],
        status="completed",
        response_text="Ready report body",
        llm_request_id="hb-test",
    )

    prepared = manager.prepare_report_delivery_for_recipient("PersonA", request_id="req-deliver")
    delivered = manager.mark_report_delivered(
        complete["report_id"],
        delivered_by="PersonA",
        request_id="req-deliver",
    )

    assert prepared["status"] == "updated"
    assert prepared["reports"][0]["body"] == "Ready report body"
    assert delivered["status"] == "updated"
    assert manager.count_pending_reports() == 0
    delivered_path = manager.delivered_reports_dir / f"{complete['report_id']}.json"
    assert delivered_path.exists()
    schedule = manager.get_schedule(result["schedule_id"])
    assert schedule["pending_report_count"] == 0


def test_schedule_manager_sensitive_report_requires_confirmation_before_body(tmp_path):
    manager, current = make_manager(tmp_path, datetime(2026, 6, 21, 8, 0, tzinfo=TAIPEI))
    result = manager.create_schedule(
        reminder_payload(
            trigger={"type": "daily", "time": "08:05", "timezone": "Asia/Taipei"},
            report={"required": True, "recipient": "PersonA", "sensitive": True},
        )
    )
    current["value"] = datetime(2026, 6, 21, 8, 6, tzinfo=TAIPEI)
    claim = manager.claim_due_job()
    manager.complete_claim(
        schedule_id=result["schedule_id"],
        claim_id=claim["claim_id"],
        status="completed",
        response_text="Sensitive body",
        llm_request_id="hb-test",
    )

    first = manager.prepare_report_delivery_for_recipient("PersonA", request_id="req-confirm")
    second = manager.prepare_report_delivery_for_recipient(
        "PersonA",
        request_id="req-deliver",
        sensitive_confirmed=True,
    )

    assert first["status"] == "needs_confirmation"
    assert "reports" not in first
    assert second["status"] == "updated"
    assert second["reports"][0]["body"] == "Sensitive body"


def test_schedule_manager_completion_without_report_only_records_run(tmp_path):
    manager, current = make_manager(tmp_path, datetime(2026, 6, 21, 8, 0, tzinfo=TAIPEI))
    result = manager.create_schedule(
        reminder_payload(trigger={"type": "daily", "time": "08:05", "timezone": "Asia/Taipei"})
    )
    current["value"] = datetime(2026, 6, 21, 8, 6, tzinfo=TAIPEI)
    claim = manager.claim_due_job()

    complete = manager.complete_claim(
        schedule_id=result["schedule_id"],
        claim_id=claim["claim_id"],
        status="completed",
        response_text="Reminder body",
        llm_request_id="hb-test",
    )

    assert complete["report_id"] is None
    assert manager.count_pending_reports() == 0
    run_dir = manager.runs_dir / result["schedule_id"]
    assert len(list(run_dir.glob("*.json"))) == 1


def test_schedule_manager_draft_confirm_and_cancel(tmp_path):
    manager, _current = make_manager(tmp_path, datetime(2026, 6, 21, 10, 0, tzinfo=TAIPEI))
    payload = {
        "operation": "create",
        "source": "conversation",
        "created_by": "PersonA",
        "draft": reminder_payload(
            report={"required": True, "recipient": "PersonA", "sensitive": False}
        ),
    }

    draft = manager.draft_create(payload)
    confirmed = manager.draft_confirm(draft["draft_id"])
    cancel_missing = manager.draft_cancel("draft_missing")

    assert draft["status"] == "needs_confirmation"
    assert confirmed["status"] == "created"
    assert confirmed["operation"] == "draft_confirm"
    assert cancel_missing["status"] == "cancelled"


def test_schedule_manager_rejects_record_id_path_traversal(tmp_path):
    manager, _current = make_manager(tmp_path, datetime(2026, 6, 21, 10, 0, tzinfo=TAIPEI))
    outside_draft = manager.state_dir / "victim.json"
    outside_schedule = manager.state_dir / "schedule-victim.json"
    outside_draft.write_text('{"status": "untouched"}', encoding="utf-8")
    outside_schedule.write_text('{"status": "untouched"}', encoding="utf-8")

    cancelled = manager.draft_cancel("../../victim")
    deleted = manager.delete_schedule("../../schedule-victim")

    assert cancelled["status"] == "needs_clarification"
    assert deleted["status"] == "blocked"
    assert json.loads(outside_draft.read_text(encoding="utf-8"))["status"] == "untouched"
    assert outside_schedule.exists()


def test_schedule_manager_low_risk_self_reminder_can_undo(tmp_path):
    manager, _current = make_manager(tmp_path, datetime(2026, 6, 21, 10, 0, tzinfo=TAIPEI))
    payload = {
        "operation": "create",
        "source": "conversation",
        "created_by": "PersonA",
        "original_text": "Remind me to drink water at 8 pm.",
        "draft": reminder_payload(),
    }

    created = manager.draft_create(payload)
    undone = manager.undo(created["operation_id"])

    assert created["status"] == "created"
    assert created["undo_until"]
    assert undone["status"] == "deleted"
    assert manager.get_schedule(created["schedule_id"]) is None


def test_schedule_manager_blocks_delete_for_active_claim(tmp_path):
    manager, current = make_manager(tmp_path, datetime(2026, 6, 21, 8, 0, tzinfo=TAIPEI))
    result = manager.create_schedule(
        reminder_payload(trigger={"type": "daily", "time": "08:05", "timezone": "Asia/Taipei"})
    )
    current["value"] = datetime(2026, 6, 21, 8, 6, tzinfo=TAIPEI)
    manager.claim_due_job()

    deleted = manager.delete_schedule(result["schedule_id"])

    assert deleted["status"] == "blocked"
