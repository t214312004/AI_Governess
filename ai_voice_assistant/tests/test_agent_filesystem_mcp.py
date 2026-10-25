from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

from tools import agent_filesystem_mcp as mcp


@pytest.fixture
def scoped_server(tmp_path):
    workspace = tmp_path / "workspace 空間"
    external = tmp_path / "Downloads 測試"
    workspace.mkdir()
    external.mkdir()
    server = mcp.FilesystemMCPServer(workspace, [external])
    server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
    server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return server, workspace, external


def call(server, name, **arguments):
    return server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}})


def content(response):
    return json.loads(response["result"]["content"][0]["text"])


def test_initialization_versions_and_required_lifecycle(tmp_path):
    server = mcp.FilesystemMCPServer(tmp_path)
    assert server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["error"]["code"] == -32002
    result = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tools = server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]
    assert {tool["name"] for tool in tools} == {"filesystem_roots", "read_text_file", "read_image_file", "list_directory", "write_text_file", "edit_text_file"}
    assert not any("shell" in tool["name"] for tool in tools)


@pytest.mark.parametrize("roots", ["not json", "{}", '["relative"]', "[true]", '[""]'])
def test_invalid_environment_scope_is_rejected(tmp_path, roots):
    with pytest.raises((mcp.FilesystemError, OSError)):
        mcp.FilesystemMCPServer.from_env({mcp.WORKSPACE_ENV: str(tmp_path), mcp.ROOTS_ENV: roots})


def test_environment_requires_workspace_and_never_defaults_to_cwd():
    with pytest.raises(mcp.FilesystemError):
        mcp.FilesystemMCPServer.from_env({})


def test_volume_root_is_not_an_implicit_unrestricted_proxy(tmp_path):
    with pytest.raises(mcp.FilesystemError):
        mcp.FilesystemMCPServer(tmp_path, [Path(tmp_path.anchor)])


def test_workspace_external_root_and_line_offsets(scoped_server):
    server, workspace, external = scoped_server
    (external / "文字.txt").write_bytes("一\r\n二\r\n三\r\n".encode("utf-8"))
    result = content(call(server, "read_text_file", path=str(external / "文字.txt"), offset=1, limit=1))
    assert result["text"] == "二\r\n"
    assert result["offset"] == 1
    assert result["total_lines"] == 3
    assert result["truncated"] is True
    assert result["sha256"] == hashlib.sha256((external / "文字.txt").read_bytes()).hexdigest()
    roots = content(call(server, "filesystem_roots"))
    assert roots["roots"] == [str(workspace.resolve()), str(external.resolve())]


@pytest.mark.parametrize("tool,args", [
    ("read_text_file", {}), ("read_image_file", {}), ("list_directory", {}),
    ("write_text_file", {"text": "SHOULD_NOT_WRITE"}),
    ("edit_text_file", {"old_text": "outside", "new_text": "SHOULD_NOT_WRITE"}),
])
def test_path_traversal_and_prefix_sibling_are_denied(scoped_server, tool, args):
    server, workspace, _ = scoped_server
    outside = workspace.parent / (workspace.name + "-sibling")
    outside.mkdir()
    target = outside / "file.txt"
    target.write_text("outside", encoding="utf-8")
    for path in [str(target), str(Path("..") / outside.name / "file.txt")]:
        response = call(server, tool, path=path, **args)
        assert response["result"]["isError"] is True
        assert "ACCESS_DENIED" in content(response)["error"]
    assert target.read_text(encoding="utf-8") == "outside"


def test_link_cannot_escape_scope_or_make_listing_follow_private_target(scoped_server):
    server, workspace, _ = scoped_server
    outside = workspace.parent / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("SYNTHETIC_SECRET", encoding="utf-8")
    link = workspace / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        # NTFS junctions do not require the Windows symbolic-link privilege.
        created = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, timeout=10)
        if created.returncode:
            pytest.skip("Current filesystem does not support directory links")
    try:
        response = call(server, "read_text_file", path="escape/secret.txt")
        assert "ACCESS_DENIED" in content(response)["error"]
        response = call(server, "write_text_file", path="escape/new.txt", text="must not write")
        assert "ACCESS_DENIED" in content(response)["error"]
        assert not (outside / "new.txt").exists()
        listing = content(call(server, "list_directory", path="."))
        assert {"name": "escape", "type": "inaccessible"} in listing["entries"]
    finally:
        if link.is_symlink():
            link.unlink()
        else:
            link.rmdir()


def test_write_and_edit_are_atomic_and_preserve_utf8_bom_and_crlf(scoped_server):
    server, workspace, external = scoped_server
    target = external / "edit.txt"
    original = b"\xef\xbb\xbf" + "first\r\n原文\r\n".encode("utf-8")
    target.write_bytes(original)
    response = call(server, "edit_text_file", path=str(target), old_text="原文", new_text="更新", expected_sha256=hashlib.sha256(original).hexdigest())
    assert response["result"]["isError"] is False
    assert target.read_bytes() == b"\xef\xbb\xbf" + "first\r\n更新\r\n".encode("utf-8")
    assert not list(external.glob(".governess-mcp-*"))
    response = call(server, "write_text_file", path="new/sub.txt", text="建立", create_parents=True)
    assert response["result"]["isError"] is False
    assert (workspace / "new/sub.txt").read_bytes() == "建立".encode("utf-8")
    response = call(server, "write_text_file", path="new/sub.txt", text="replace")
    assert "FILE_EXISTS" in content(response)["error"]
    assert (workspace / "new/sub.txt").read_bytes() == "建立".encode("utf-8")


def test_stale_hash_ambiguous_and_missing_edit_do_not_mutate(scoped_server):
    server, workspace, _ = scoped_server
    target = workspace / "edit.txt"
    target.write_text("same same", encoding="utf-8")
    for args, code in [
        ({"old_text": "same", "new_text": "new"}, "MATCH_ERROR"),
        ({"old_text": "missing", "new_text": "new"}, "MATCH_ERROR"),
        ({"old_text": "same same", "new_text": "new", "expected_sha256": "stale"}, "CONFLICT"),
    ]:
        assert code in content(call(server, "edit_text_file", path="edit.txt", **args))["error"]
    assert "CONFLICT" in content(call(server, "write_text_file", path="edit.txt", text="new", overwrite=True, expected_sha256="stale"))["error"]
    assert target.read_text(encoding="utf-8") == "same same"


def test_atomic_replace_failure_preserves_original_and_cleans_staging_file(scoped_server, monkeypatch):
    server, workspace, _ = scoped_server
    target = workspace / "existing.txt"
    target.write_text("original", encoding="utf-8")

    def fail_replace(*args):
        raise PermissionError("SYNTHETIC_PRIVATE_DIAGNOSTIC")

    monkeypatch.setattr(mcp.os, "replace", fail_replace)
    response = call(server, "edit_text_file", path="existing.txt", old_text="original", new_text="replacement")
    assert response["result"]["isError"] is True
    assert "SYNTHETIC_PRIVATE_DIAGNOSTIC" not in json.dumps(response)
    assert target.read_text(encoding="utf-8") == "original"
    assert not list(workspace.glob(".governess-mcp-*"))


def test_atomic_create_does_not_overwrite_a_concurrent_new_file(scoped_server, monkeypatch):
    server, workspace, _ = scoped_server
    link = mcp.os.link

    def concurrent_create(source, target):
        Path(target).write_text("concurrent creator", encoding="utf-8")
        return link(source, target)

    monkeypatch.setattr(mcp.os, "link", concurrent_create)
    response = call(server, "write_text_file", path="new.txt", text="tool content")
    assert response["result"]["isError"] is True
    assert (workspace / "new.txt").read_text(encoding="utf-8") == "concurrent creator"
    assert not list(workspace.glob(".governess-mcp-*"))


def test_image_returns_actual_mcp_image_content(scoped_server):
    server, _, external = scoped_server
    target = external / "synthetic.png"
    Image.new("RGB", (3, 2), "red").save(target)
    response = call(server, "read_image_file", path=str(target))
    image = response["result"]["content"][0]
    assert response["result"]["isError"] is False
    assert image["type"] == "image"
    assert image["mimeType"] == "image/png"
    assert base64.b64decode(image["data"]) == target.read_bytes()


def test_bad_images_encoding_and_size_errors_do_not_echo_file_content(scoped_server, monkeypatch):
    server, workspace, _ = scoped_server
    private_marker = b"SYNTHETIC_PRIVATE_BYTES\xff"
    (workspace / "bad.png").write_bytes(private_marker)
    response = call(server, "read_image_file", path="bad.png")
    assert response["result"]["isError"] is True
    assert "SYNTHETIC_PRIVATE_BYTES" not in json.dumps(response)
    response = call(server, "read_text_file", path="bad.png")
    assert "INVALID_TEXT_ENCODING" in content(response)["error"]
    monkeypatch.setattr(mcp, "MAX_IMAGE_BYTES", 2)
    assert "FILE_TOO_LARGE" in content(call(server, "read_image_file", path="bad.png"))["error"]
    monkeypatch.setattr(mcp, "MAX_TEXT_BYTES", 2)
    assert "FILE_TOO_LARGE" in content(call(server, "read_text_file", path="bad.png"))["error"]


@pytest.mark.parametrize("name,arguments", [
    ("read_text_file", {"path": "x", "offset": True}),
    ("read_text_file", {"path": "x", "offset": -1}),
    ("read_text_file", {"path": "x", "limit": 4001}),
    ("edit_text_file", {"path": "x", "old_text": "", "new_text": "y"}),
    ("write_text_file", {"path": "x", "text": "x", "overwrite": "yes"}),
    ("read_text_file", {"path": "x", "extra": "value"}),
    ("unknown", {}),
])
def test_invalid_tool_arguments_are_protocol_errors(scoped_server, name, arguments):
    assert call(scoped_server[0], name, **arguments)["error"]["code"] == -32602


@pytest.mark.skipif(os.name != "nt", reason="Win32 filesystem semantics")
@pytest.mark.parametrize("path", ["NUL", "name.txt:stream", "sub/name.txt:stream"])
def test_windows_device_and_ads_paths_are_denied(scoped_server, path):
    response = call(scoped_server[0], "write_text_file", path=path, text="test")
    assert "ACCESS_DENIED" in content(response)["error"]


def test_stdio_end_to_end_only_emits_protocol_and_exits_on_eof(tmp_path):
    script = Path(mcp.__file__).resolve()
    env = dict(os.environ, **{mcp.WORKSPACE_ENV: str(tmp_path), mcp.ROOTS_ENV: "[]"})
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "write_text_file", "arguments": {"path": "中文.txt", "text": "SYNTHETIC_CANARY"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "read_text_file", "arguments": {"path": "中文.txt"}}},
    ]
    completed = subprocess.run([sys.executable, "-B", str(script)], input=("\n".join(json.dumps(r, ensure_ascii=False) for r in requests) + "\n").encode("utf-8"), env=env, capture_output=True, timeout=10)
    assert completed.returncode == 0
    assert completed.stderr == b""
    responses = [json.loads(line) for line in completed.stdout.decode("utf-8").splitlines()]
    assert [response["id"] for response in responses] == [1, 2, 3]
    assert content(responses[2])["text"] == "SYNTHETIC_CANARY"
    assert (tmp_path / "中文.txt").read_text(encoding="utf-8") == "SYNTHETIC_CANARY"


def test_cli_missing_scope_fails_without_private_diagnostics(tmp_path):
    env = dict(os.environ)
    env.pop(mcp.WORKSPACE_ENV, None)
    completed = subprocess.run([sys.executable, "-B", mcp.__file__], input=b"", env=env, capture_output=True, timeout=10)
    assert completed.returncode == 2
    assert completed.stdout == b""
    assert completed.stderr.decode("utf-8").strip() == "filesystem_mcp_startup_error: invalid filesystem scope configuration"


def test_cli_help_describes_environment_without_starting_protocol():
    completed = subprocess.run([sys.executable, "-B", mcp.__file__, "--help"], capture_output=True, timeout=10)
    assert completed.returncode == 0
    assert mcp.ROOTS_ENV in completed.stdout.decode("utf-8")
