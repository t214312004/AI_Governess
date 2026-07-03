from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from PIL import Image


def load_whiteboard_tool(monkeypatch, tmp_path):
    app_dir = tmp_path / "app"
    payload_dir = app_dir / "agent_workspace" / "tool_payloads" / "whiteboard"
    payload_dir.mkdir(parents=True)
    monkeypatch.setenv("AI_GOVERNESS_APP_DIR", str(app_dir))
    monkeypatch.chdir(app_dir / "agent_workspace")
    tool_path = (
        Path(__file__).resolve().parents[1]
        / "agent_workspace_template"
        / "tools"
        / "whiteboard_tool.py"
    )
    spec = importlib.util.spec_from_file_location("whiteboard_tool_test_module", tool_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, payload_dir


def write_payload(payload_dir, name, payload):
    path = payload_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_whiteboard_tool_show_markdown_status_get_and_close(monkeypatch, tmp_path):
    module, payload_dir = load_whiteboard_tool(monkeypatch, tmp_path)
    write_payload(payload_dir, "payload.json", {"title": "白板", "markdown": "# 白板\n\n- A"})

    shown = module.run(["show-markdown", "--payload", "tool_payloads/whiteboard/payload.json"])
    status = module.run(["status"])
    content = module.run(["get-content", "--max-chars", "20"])
    closed = module.run(["close", "--content-id", shown["content_id"]])

    assert shown["status"] == "shown"
    assert status["status"] == "active"
    assert content["status"] == "ok"
    assert content["markdown"].startswith("# 白板")
    assert closed["status"] == "closed"
    assert module.run(["status"])["status"] == "empty"


def test_whiteboard_tool_accepts_utf8_bom_payload(monkeypatch, tmp_path):
    module, payload_dir = load_whiteboard_tool(monkeypatch, tmp_path)
    payload_path = payload_dir / "bom_payload.json"
    payload_path.write_bytes(
        b"\xef\xbb\xbf"
        + json.dumps({"title": "BOM", "markdown": "# BOM"}, ensure_ascii=False).encode("utf-8")
    )

    shown = module.run(["show-markdown", "--payload", "tool_payloads/whiteboard/bom_payload.json"])

    assert shown["status"] == "shown"


def test_whiteboard_tool_show_image(monkeypatch, tmp_path):
    module, payload_dir = load_whiteboard_tool(monkeypatch, tmp_path)
    image_dir = payload_dir / "assets"
    image_dir.mkdir()
    Image.new("RGB", (32, 24), color="white").save(image_dir / "sample.png")
    write_payload(
        payload_dir,
        "image.json",
        {
            "title": "圖片",
            "image_path": "tool_payloads/whiteboard/assets/sample.png",
            "alt_text": "sample",
        },
    )

    shown = module.run(["show-image", "--payload", "tool_payloads/whiteboard/image.json"])
    content = module.run(["get-content"])

    assert shown["status"] == "shown"
    assert shown["content_type"] == "image"
    assert content["width"] == 32
    assert content["height"] == 24
    assert content["alt_text"] == "sample"


def test_whiteboard_tool_rejects_payload_outside_payload_root(monkeypatch, tmp_path):
    module, _payload_dir = load_whiteboard_tool(monkeypatch, tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"title": "Bad", "markdown": "# Bad"}), encoding="utf-8")

    result = module.run(["show-markdown", "--payload", str(outside)])

    assert result["status"] == "needs_clarification"
    assert "Payload must be under" in result["errors"][0]


def test_whiteboard_tool_rejects_nested_markdown_outside_payload_root(monkeypatch, tmp_path):
    module, payload_dir = load_whiteboard_tool(monkeypatch, tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("# Bad", encoding="utf-8")
    write_payload(payload_dir, "payload.json", {"title": "Bad", "markdown_path": str(outside)})

    result = module.run(["show-markdown", "--payload", "tool_payloads/whiteboard/payload.json"])

    assert result["status"] == "needs_clarification"
    assert "must be under" in result["errors"][0]


def test_whiteboard_tool_dedicated_payload_dir_override(monkeypatch, tmp_path):
    module, _payload_dir = load_whiteboard_tool(monkeypatch, tmp_path)
    custom_payload_dir = tmp_path / "custom_whiteboard_payloads"
    custom_payload_dir.mkdir()
    monkeypatch.setenv("AI_GOVERNESS_WHITEBOARD_PAYLOAD_DIR", str(custom_payload_dir))
    payload = custom_payload_dir / "payload.json"
    payload.write_text(json.dumps({"title": "Custom", "markdown": "# Custom"}), encoding="utf-8")

    result = module.run(["show-markdown", "--payload", str(payload)])

    assert result["status"] == "shown"


def test_whiteboard_guidance_documents_tool_and_boundaries():
    template_dir = Path(__file__).resolve().parents[1] / "agent_workspace_template"
    tools_text = (template_dir / "TOOLS.md").read_text(encoding="utf-8")
    agents_text = (template_dir / "AGENTS.md").read_text(encoding="utf-8")

    assert "..\\venv\\Scripts\\python.exe tools\\whiteboard_tool.py show-markdown" in tools_text
    assert "Do not directly edit `whiteboard_state/`" in tools_text
    assert "display-only" in tools_text
    assert "Do not include raw HTML" in tools_text
    assert "Markdown image syntax" in tools_text
    assert "clickable whiteboard links" in tools_text
    assert "When a system hint says the whiteboard is active" in tools_text
    assert "Whiteboard 操作" in agents_text
    assert "格式化文字 whiteboard 使用 Markdown" in agents_text
