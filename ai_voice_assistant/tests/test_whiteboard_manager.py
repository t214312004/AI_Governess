from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PIL import Image

from core.whiteboard_manager import WhiteboardManager


def make_manager(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    payload_root = app_dir / "agent_workspace" / "tool_payloads" / "whiteboard"
    payload_root.mkdir(parents=True)
    monkeypatch.chdir(app_dir / "agent_workspace")
    manager = WhiteboardManager(
        app_dir,
        payload_root=payload_root,
        max_markdown_bytes=2000,
        max_image_bytes=200000,
        max_image_pixels=1000000,
        now_func=lambda: datetime(2026, 6, 28, 12, 34, 56),
    )
    return manager, payload_root


def test_show_markdown_creates_sanitized_active_state(monkeypatch, tmp_path):
    manager, _payload_root = make_manager(tmp_path, monkeypatch)

    result = manager.show_markdown(
        {
            "title": "今日安排",
            "markdown": "# 今日安排\n\n請看 [OpenAI](https://example.com)。\n<div>提醒</div>",
        }
    )
    content = manager.get_content(max_chars=1000)
    active = manager.get_active()

    assert result["status"] == "shown"
    assert active["content_type"] == "markdown"
    assert active["title"] == "今日安排"
    assert "sanitizer" in active
    assert "[OpenAI]" not in content["markdown"]
    assert "OpenAI" in content["markdown"]
    assert "https://" not in content["markdown"]
    assert "&lt;div&gt;提醒&lt;/div&gt;" in content["markdown"]


def test_show_markdown_file_must_be_under_payload_root(monkeypatch, tmp_path):
    manager, _payload_root = make_manager(tmp_path, monkeypatch)
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside", encoding="utf-8")

    result = manager.show_markdown({"title": "Bad", "markdown_path": str(outside)})

    assert result["status"] == "needs_clarification"
    assert "must be under" in result["errors"][0]


def test_show_markdown_file_accepts_utf8_bom(monkeypatch, tmp_path):
    manager, payload_root = make_manager(tmp_path, monkeypatch)
    markdown_path = payload_root / "bom.md"
    markdown_path.write_bytes(b"\xef\xbb\xbf# BOM")

    result = manager.show_markdown(
        {"title": "BOM", "markdown_path": "tool_payloads/whiteboard/bom.md"}
    )
    content = manager.get_content()

    assert result["status"] == "shown"
    assert content["markdown"].startswith("# BOM")
    assert not content["markdown"].startswith("\ufeff")


def test_show_markdown_rejects_markdown_image_syntax(monkeypatch, tmp_path):
    manager, _payload_root = make_manager(tmp_path, monkeypatch)

    result = manager.show_markdown({"title": "Bad", "markdown": "![x](https://example.com/a.png)"})

    assert result["status"] == "needs_clarification"
    assert "Markdown image syntax" in result["errors"][0]


def test_show_image_materializes_metadata_without_binary(monkeypatch, tmp_path):
    manager, payload_root = make_manager(tmp_path, monkeypatch)
    image_path = payload_root / "sample.png"
    Image.new("RGB", (120, 80), color="white").save(image_path)

    result = manager.show_image(
        {
            "title": "圖片",
            "image_path": "tool_payloads/whiteboard/sample.png",
            "alt_text": "測試圖片",
        }
    )
    content = manager.get_content()
    active = manager.get_active()

    assert result["status"] == "shown"
    assert result["content_type"] == "image"
    assert active["image_path"].endswith("/image.png")
    assert content["status"] == "ok"
    assert content["alt_text"] == "測試圖片"
    assert content["width"] == 120
    assert content["height"] == 80
    returned_path = Path(content["image_path"])
    assert returned_path.is_absolute()
    assert returned_path.is_file()
    assert returned_path.suffix == ".png"
    assert returned_path == manager.resolve_asset_path(active["image_path"])
    returned_path.relative_to(manager.assets_dir.resolve())
    assert "image" not in content


def test_show_image_rejects_nested_path_outside_payload_root(monkeypatch, tmp_path):
    manager, _payload_root = make_manager(tmp_path, monkeypatch)
    outside = tmp_path / "outside.png"
    Image.new("RGB", (1, 1), color="white").save(outside)

    result = manager.show_image({"title": "Bad", "image_path": str(outside)})

    assert result["status"] == "needs_clarification"
    assert "must be under" in result["errors"][0]


def test_close_with_stale_content_id_is_blocked(monkeypatch, tmp_path):
    manager, _payload_root = make_manager(tmp_path, monkeypatch)
    shown = manager.show_markdown({"title": "A", "markdown": "# A"})
    asset_dir = manager._asset_dir_from_state(manager.get_active())

    blocked = manager.close("wb_stale")
    still_active = manager.status()

    assert blocked["status"] == "blocked"
    assert asset_dir.exists()
    assert still_active["status"] == "active"
    closed = manager.close(shown["content_id"])
    assert closed["status"] == "closed"
    assert manager.status()["status"] == "empty"
    assert not asset_dir.exists()


def test_new_show_deletes_previous_active_asset_dir(monkeypatch, tmp_path):
    manager, _payload_root = make_manager(tmp_path, monkeypatch)
    first = manager.show_markdown({"title": "A", "markdown": "# A"})
    first_asset_dir = manager._asset_dir_from_state(manager.get_active())
    first_content_path = first_asset_dir / "content.md"
    assert first_content_path.exists()

    second = manager.show_markdown({"title": "B", "markdown": "# B"})
    second_asset_dir = manager._asset_dir_from_state(manager.get_active())

    assert first["content_id"] != second["content_id"]
    assert not first_asset_dir.exists()
    assert second_asset_dir.exists()
    assert (second_asset_dir / "content.md").exists()


def test_asset_cleanup_refuses_paths_outside_assets_root(monkeypatch, tmp_path):
    manager, _payload_root = make_manager(tmp_path, monkeypatch)
    outside = tmp_path / "outside_asset"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")

    deleted = manager._delete_asset_dir_for_state(
        {
            "content_id": "wb_bad",
            "asset_dir": str(outside),
        }
    )

    assert deleted is False
    assert outside.exists()
    assert (outside / "keep.txt").exists()


def test_get_content_truncates_markdown(monkeypatch, tmp_path):
    manager, _payload_root = make_manager(tmp_path, monkeypatch)
    manager.show_markdown({"title": "Long", "markdown": "abcdef"})

    content = manager.get_content(max_chars=3)

    assert content["markdown"] == "abc"
    assert content["truncated"] is True
    assert content["max_chars"] == 3


def test_get_content_rejects_tampered_path_outside_assets(monkeypatch, tmp_path):
    manager, _payload_root = make_manager(tmp_path, monkeypatch)
    manager.show_markdown({"title": "Safe", "markdown": "safe"})
    outside = tmp_path / "secret.md"
    outside.write_text("secret", encoding="utf-8")
    active = manager.get_active()
    active["markdown_path"] = str(outside)
    manager._write_active(active)

    content = manager.get_content()

    assert content["status"] == "blocked"
    assert "secret" not in json.dumps(content, ensure_ascii=False)


def test_get_content_rejects_tampered_image_path_outside_assets(monkeypatch, tmp_path):
    manager, payload_root = make_manager(tmp_path, monkeypatch)
    source_path = payload_root / "sample.png"
    Image.new("RGB", (8, 6), color="white").save(source_path)
    manager.show_image(
        {
            "title": "Safe image",
            "image_path": "tool_payloads/whiteboard/sample.png",
        }
    )
    outside = tmp_path / "secret.png"
    Image.new("RGB", (1, 1), color="black").save(outside)
    active = manager.get_active()
    active["image_path"] = str(outside)
    manager._write_active(active)

    content = manager.get_content()

    assert content["status"] == "blocked"
    assert str(outside) not in json.dumps(content, ensure_ascii=False)


def test_get_content_rejects_missing_image_asset(monkeypatch, tmp_path):
    manager, payload_root = make_manager(tmp_path, monkeypatch)
    source_path = payload_root / "sample.png"
    Image.new("RGB", (8, 6), color="white").save(source_path)
    manager.show_image(
        {
            "title": "Missing image",
            "image_path": "tool_payloads/whiteboard/sample.png",
        }
    )
    active = manager.get_active()
    display_path = manager.resolve_asset_path(active["image_path"])
    display_path.unlink()

    content = manager.get_content()

    assert content["status"] == "blocked"
    assert "image_path" not in content
