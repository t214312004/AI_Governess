from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def load_schedule_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_GOVERNESS_APP_DIR", str(tmp_path))
    payload_dir = tmp_path / "agent_workspace" / "tool_payloads" / "schedule"
    payload_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path / "agent_workspace")
    tool_path = (
        Path(__file__).resolve().parents[1]
        / "agent_workspace_template"
        / "tools"
        / "schedule_tool.py"
    )
    spec = importlib.util.spec_from_file_location("schedule_tool_test_module", tool_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, payload_dir


def write_payload(payload_dir, name, payload):
    path = payload_dir / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def valid_payload(report_required=False):
    return {
        "operation": "create",
        "source": "conversation",
        "created_by": "PersonA",
        "original_text": "schedule this",
        "draft": {
            "title": "Water",
            "task_prompt": "Remind PersonA to drink water.",
            "created_by": "PersonA",
            "trigger": {
                "type": "once",
                "date": "2099-06-21",
                "time": "20:00",
                "timezone": "Asia/Taipei",
            },
            "report": {
                "required": report_required,
                "recipient": "PersonA" if report_required else None,
                "sensitive": False,
            },
        },
    }


def test_schedule_tool_draft_create_fast_path_and_list(monkeypatch, tmp_path):
    module, payload_dir = load_schedule_tool(monkeypatch, tmp_path)
    write_payload(payload_dir, "payload.json", valid_payload(report_required=False))

    created = module.run(["draft-create", "--payload", "tool_payloads/schedule/payload.json"])
    listed = module.run(["list"])

    assert created["status"] == "created"
    assert created["operation_id"]
    assert listed["status"] == "listed"
    assert listed["schedules"][0]["schedule_id"] == created["schedule_id"]


def test_schedule_tool_requires_confirmation_for_report_schedule(monkeypatch, tmp_path):
    module, payload_dir = load_schedule_tool(monkeypatch, tmp_path)
    write_payload(payload_dir, "report.json", valid_payload(report_required=True))

    draft = module.run(["draft-create", "--payload", "tool_payloads/schedule/report.json"])
    confirmed = module.run(["draft-confirm", "--draft-id", draft["draft_id"]])

    assert draft["status"] == "needs_confirmation"
    assert confirmed["status"] == "created"
    assert confirmed["operation"] == "draft_confirm"


def test_schedule_tool_rejects_payload_outside_payload_root(monkeypatch, tmp_path):
    module, _payload_dir = load_schedule_tool(monkeypatch, tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(valid_payload()), encoding="utf-8")

    result = module.run(["draft-create", "--payload", str(outside)])

    assert result["status"] == "needs_clarification"
    assert "Payload must be under" in result["errors"][0]


def test_schedule_tool_delete_refuses_active_claim(monkeypatch, tmp_path):
    module, payload_dir = load_schedule_tool(monkeypatch, tmp_path)
    write_payload(payload_dir, "payload.json", valid_payload(report_required=False))
    created = module.run(["draft-create", "--payload", "tool_payloads/schedule/payload.json"])

    manager = module._manager()
    schedule = manager.get_schedule(created["schedule_id"])
    schedule["claim_id"] = "claim_active"
    schedule["claimed_at"] = manager.now().isoformat()
    manager._atomic_write_json(manager._schedule_path(created["schedule_id"]), schedule)

    deleted = module.run(["delete", "--schedule-id", created["schedule_id"]])

    assert deleted["status"] == "blocked"


def test_schedule_tool_blocks_report_body_and_delivery_marking(monkeypatch, tmp_path):
    module, _payload_dir = load_schedule_tool(monkeypatch, tmp_path)

    listed = module.run(["reports-list", "--recipient", "PersonA", "--include-body"])
    delivered = module.run(["report-deliver", "--report-id", "report_1", "--delivered-by", "PersonA"])

    assert listed["status"] == "blocked"
    assert delivered["status"] == "blocked"


def test_schedule_guidance_documents_tool_and_json_boundary():
    template_dir = Path(__file__).resolve().parents[1] / "agent_workspace_template"
    tools_text = (template_dir / "TOOLS.md").read_text(encoding="utf-8")
    agents_text = (template_dir / "AGENTS.md").read_text(encoding="utf-8")

    assert "python tools/schedule_tool.py draft-create" in tools_text
    assert "Do not write schedule, draft, run, or report JSON files directly" in tools_text
    assert "recipient matching, report-body injection, and delivered marking" in tools_text
    assert "do not use it to reveal report" in tools_text
    assert "Schedule Operations" in agents_text
    assert "Do not directly edit schedule, draft, run, or report JSON files" in agents_text
