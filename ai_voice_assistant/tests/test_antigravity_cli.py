# ai_voice_assistant/tests/test_antigravity_cli.py
import asyncio
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from llm.antigravity_cli_client import AntigravityCLIClient, _looks_like_cli_error, _strip_ansi
from llm.base_client import STREAM_ACTIVITY_KEEPALIVE


def test_antigravity_client_init_defaults():
    """驗證預設參數正確設定。"""
    client = AntigravityCLIClient()
    assert client.project_dir.endswith("agent_workspace")
    assert client.session_id is None
    assert client._pty_process is None
    assert client._cancel_flag is False


@pytest.mark.asyncio
async def test_ensure_ready_raises_when_agy_not_found(mocker):
    """當 agy 執行檔不存在時 raise RuntimeError。"""
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value=None)
    client = AntigravityCLIClient()
    with pytest.raises(RuntimeError, match="本機環境找不到 agy 執行檔"):
        await client.ensure_ready()


@pytest.mark.asyncio
async def test_ensure_ready_succeeds_when_agy_found(mocker):
    """當 agy 執行檔存在時回傳 True。"""
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="C:\\bin\\agy.exe")
    client = AntigravityCLIClient()
    assert await client.ensure_ready() is True


@pytest.mark.asyncio
async def test_ensure_ready_does_not_resume_old_conversation(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="C:\\bin\\agy.exe")
    get_latest = mocker.patch.object(
        AntigravityCLIClient,
        "_get_latest_conversation_id",
        return_value="latest-session",
    )

    client = AntigravityCLIClient()

    assert await client.ensure_ready() is True
    assert client.session_id is None
    get_latest.assert_not_called()


def test_build_command_string_does_not_auto_resume(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")

    client = AntigravityCLIClient()
    command = client._build_command_string("hello")

    assert client.session_id is None
    assert "--conversation" not in command


def test_build_command_string_includes_explicit_session_id(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")

    client = AntigravityCLIClient()
    command = client._build_command_string("hello", session_id="latest-session")

    assert "--conversation latest-session" in command


def test_get_latest_conversation_id_reads_cli_cache_for_project(tmp_path, mocker):
    home = tmp_path / "home"
    project_dir = tmp_path / "agent_workspace"
    conv_dir = home / ".gemini" / "antigravity-cli" / "conversations"
    cache_dir = home / ".gemini" / "antigravity-cli" / "cache"
    conv_dir.mkdir(parents=True)
    cache_dir.mkdir(parents=True)
    project_dir.mkdir()

    conv_id = "518e8179-70ed-4c0d-947f-b337a27f8fff"
    (conv_dir / f"{conv_id}.pb").write_text("conversation", encoding="utf-8")
    (cache_dir / "last_conversations.json").write_text(
        json.dumps({str(project_dir): conv_id}),
        encoding="utf-8",
    )
    mocker.patch("llm.antigravity_cli_client.os.path.expanduser", return_value=str(home))

    client = AntigravityCLIClient(project_dir=str(project_dir))

    assert client._get_latest_conversation_id() == conv_id


def test_get_latest_conversation_id_rejects_missing_cached_conversation(tmp_path, mocker):
    home = tmp_path / "home"
    project_dir = tmp_path / "agent_workspace"
    cache_dir = home / ".gemini" / "antigravity-cli" / "cache"
    cache_dir.mkdir(parents=True)
    project_dir.mkdir()

    (cache_dir / "last_conversations.json").write_text(
        json.dumps({str(project_dir): "missing-session"}),
        encoding="utf-8",
    )
    mocker.patch("llm.antigravity_cli_client.os.path.expanduser", return_value=str(home))

    client = AntigravityCLIClient(project_dir=str(project_dir))

    assert client._get_latest_conversation_id() is None


def test_get_resume_session_id_clears_stale_session(mocker):
    client = AntigravityCLIClient()
    client.session_id = "stale-session"
    client._last_cleaned_output = "old-output"
    mocker.patch.object(client, "_conversation_exists", return_value=False)

    assert client._get_resume_session_id() is None
    assert client.session_id is None
    assert client._last_cleaned_output == ""


@pytest.mark.asyncio
async def test_refresh_session_clears_session_id():
    """refresh_session 清空 session_id。"""
    client = AntigravityCLIClient()
    client.session_id = "old-session"
    result = await client.refresh_session()
    assert result is True
    assert client.session_id is None


@pytest.mark.asyncio
async def test_aclose_and_cancel():
    """aclose() 與 cancel() 設置 flag 並妥善終止 PTY 進程。"""
    client = AntigravityCLIClient()
    mock_pty = MagicMock()
    client._pty_process = mock_pty

    await client.cancel()
    assert client._cancel_flag is True
    mock_pty.terminate.assert_called_once()
    assert client._pty_process is None


def test_strip_ansi_removes_escape_sequences():
    """驗證 _strip_ansi 能清除 ANSI escape sequences。"""
    raw = "\x1b[1t\x1b[c\x1b[?1004h\x1b[?9001hHello World\r\n"
    assert _strip_ansi(raw) == "Hello World\r\n"


def test_strip_ansi_preserves_plain_text():
    """純文字不應被修改。"""
    plain = "這是一段普通的中文文字。"
    assert _strip_ansi(plain) == plain


def test_strip_ansi_handles_empty_string():
    assert _strip_ansi("") == ""


def test_looks_like_cli_error_detects_timeout_output():
    assert _looks_like_cli_error("Error: timed out waiting for response")


def test_looks_like_cli_error_detects_failed_send_output():
    assert _looks_like_cli_error(
        "Error: failed to send message: trajectory not found: 5e6009f9"
    )


@pytest.mark.asyncio
async def test_send_message_success(mocker):
    """驗證 send_message 透過 PTY 成功取得回覆並更新 session_id。"""
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")

    # 模擬 _run_pty_blocking 回傳結果
    fake_raw = "\x1b[1t\x1b[cHi there!\r\nHow can I help?\r\n"
    mocker.patch.object(
        AntigravityCLIClient,
        "_run_pty_blocking",
        return_value=(fake_raw, 0),
    )

    # 模擬自動偵測 latest conversation id
    mocker.patch.object(
        AntigravityCLIClient,
        "_get_latest_conversation_id",
        return_value="new-detected-uuid",
    )

    client = AntigravityCLIClient()
    results = []
    async for chunk in client.send_message("hello"):
        if chunk != STREAM_ACTIVITY_KEEPALIVE:
            results.append(chunk)

    # 檢查是否正常讀取並清理 ANSI 後輸出
    assert len(results) == 1
    assert "Hi there!" in results[0]
    assert "How can I help?" in results[0]
    # 不應包含 ANSI escape
    assert "\x1b" not in results[0]
    # 檢查對話結束後是否更新了 session_id
    assert client.session_id == "new-detected-uuid"


@pytest.mark.asyncio
async def test_send_message_yields_only_incremental_output_when_resuming(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")
    mocker.patch.object(
        AntigravityCLIClient,
        "_run_pty_blocking",
        return_value=("FIRST\r\nSECOND\r\n", 0),
    )
    mocker.patch.object(
        AntigravityCLIClient,
        "_get_latest_conversation_id",
        return_value="existing-session",
    )

    client = AntigravityCLIClient()
    client.session_id = "existing-session"
    client._last_cleaned_output = "FIRST"
    mocker.patch.object(client, "_conversation_exists", return_value=True)

    results = []
    async for chunk in client.send_message("hello"):
        if chunk != STREAM_ACTIVITY_KEEPALIVE:
            results.append(chunk)

    assert results == ["SECOND"]
    assert client._last_cleaned_output == "FIRST\r\nSECOND"


@pytest.mark.asyncio
async def test_send_message_retries_once_when_cached_session_is_stale(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")
    run_pty = mocker.patch.object(
        AntigravityCLIClient,
        "_run_pty_blocking",
        side_effect=[
            ("Error: failed to send message: trajectory not found: old-session\r\n", 0),
            ("Fresh response\r\n", 0),
        ],
    )
    mocker.patch.object(
        AntigravityCLIClient,
        "_get_latest_conversation_id",
        return_value="new-session",
    )

    client = AntigravityCLIClient()
    client.session_id = "old-session"
    client._last_cleaned_output = "Old response"
    mocker.patch.object(client, "_conversation_exists", return_value=True)

    results = []
    async for chunk in client.send_message("hello"):
        if chunk != STREAM_ACTIVITY_KEEPALIVE:
            results.append(chunk)

    assert results == ["Fresh response"]
    assert client.session_id == "new-session"
    assert client._last_cleaned_output == "Fresh response"
    assert run_pty.call_count == 2
    first_command = run_pty.call_args_list[0].args[0]
    second_command = run_pty.call_args_list[1].args[0]
    assert "--conversation old-session" in first_command
    assert "--conversation" not in second_command


@pytest.mark.asyncio
async def test_send_message_raises_on_cli_timeout_output(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")
    mocker.patch.object(
        AntigravityCLIClient,
        "_run_pty_blocking",
        return_value=("Error: timed out waiting for response\r\n", 0),
    )
    mocker.patch.object(
        AntigravityCLIClient,
        "_get_latest_conversation_id",
        return_value=None,
    )

    client = AntigravityCLIClient()

    with pytest.raises(RuntimeError, match="timed out waiting for response"):
        async for _chunk in client.send_message("hello"):
            pass


@pytest.mark.asyncio
async def test_send_message_raises_on_cli_failed_send_output(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")
    mocker.patch.object(
        AntigravityCLIClient,
        "_run_pty_blocking",
        return_value=(
            "Error: failed to send message: trajectory not found: 5e6009f9\r\n",
            0,
        ),
    )
    mocker.patch.object(
        AntigravityCLIClient,
        "_get_latest_conversation_id",
        return_value=None,
    )

    client = AntigravityCLIClient()

    with pytest.raises(RuntimeError, match="trajectory not found"):
        async for _chunk in client.send_message("hello"):
            pass


def test_run_pty_blocking_uses_project_dir_as_cwd(mocker, tmp_path):
    from winpty import PtyProcess

    class FakePtyProcess:
        exitstatus = 0

        def isalive(self):
            return False

        def readline(self):
            return ""

    spawn = mocker.patch.object(PtyProcess, "spawn", return_value=FakePtyProcess())
    client = AntigravityCLIClient(project_dir=str(tmp_path))

    assert client._run_pty_blocking("agy -p hello") == ("", 0)
    spawn.assert_called_once_with("agy -p hello", cwd=str(tmp_path))
