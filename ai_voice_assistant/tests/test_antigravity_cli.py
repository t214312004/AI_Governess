# ai_voice_assistant/tests/test_antigravity_cli.py
import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from llm.antigravity_cli_client import AntigravityCLIClient, _strip_ansi
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
