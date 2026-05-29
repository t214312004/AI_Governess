# ai_voice_assistant/tests/test_antigravity_cli.py
import asyncio
import os
import pytest
import sqlite3
import json
from unittest.mock import AsyncMock, MagicMock, patch

from llm.antigravity_cli_client import AntigravityCLIClient
from llm.base_client import STREAM_ACTIVITY_KEEPALIVE


def test_antigravity_client_init_defaults():
    """驗證預設參數正確設定。"""
    client = AntigravityCLIClient()
    assert client.project_dir.endswith("agent_workspace")
    assert client.session_id is None
    assert client.process is None
    assert client._cancel_flag is False


def test_extract_ai_response():
    """驗證 _extract_ai_response 能夠從帶有 protobuf 雜訊的 payload 二進位中成功提取 AI 純文字。"""
    # 模擬帶有 bot-UUID 前綴與尾巴二進位雜訊的 payload 串流
    sample_payload = (
        b"\x0a\x12bot-bc62d420-f44a-4022-a37e-83262b83e56cB \xe4\xbd\xa0\xe5\xa5\xbd\xef\xbc\x81"
        b"\xe6\x88\x91\xe6\x98\xaf\xe6\xb5\x8b\xe8\xaf\x95\xe3\x80\x82\x12(bot-bc62d420-f44a-4022-a37e-83262b83e56cB"
    )
    result = AntigravityCLIClient._extract_ai_response(sample_payload)
    assert result == "你好！我是测试。"


@pytest.mark.asyncio
async def test_ensure_ready_raises_when_ls_not_found(mocker):
    """當 language_server 不存在時 raise RuntimeError。"""
    mocker.patch("llm.antigravity_cli_client.os.path.exists", return_value=False)
    client = AntigravityCLIClient()
    with pytest.raises(RuntimeError, match="Antigravity 語言伺服器未安裝"):
        await client.ensure_ready()


@pytest.mark.asyncio
async def test_ensure_ready_succeeds_when_ls_found(mocker):
    """當 language_server 存在時回傳 True。"""
    mocker.patch("llm.antigravity_cli_client.os.path.exists", return_value=True)
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
    """aclose() 與 cancel() 設置 flag 並妥善清理進程。"""
    client = AntigravityCLIClient()
    client.process = MagicMock()
    client.process.returncode = None

    mock_process = client.process
    await client.cancel()
    assert client._cancel_flag is True
    mock_process.terminate.assert_called_once()
    assert client.process is None


@pytest.mark.asyncio
async def test_send_message_success(mocker, tmp_path):
    """驗證 send_message 流程能成功建立 session 並從 SQLite 提取回覆。"""
    mocker.patch("llm.antigravity_cli_client.os.path.exists", return_value=True)

    # 模擬進程 metadata JSON 輸出 (含有新的 conversationId)
    metadata_json = {
        "response": {
            "conversationMetadata": {
                "metadata": {
                    "sourceMetadata": {
                        "tool": {
                            "conversationId": "test-session-1234"
                        }
                    }
                }
            }
        }
    }
    stdout_data = json.dumps(metadata_json).encode("utf-8")

    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.stdout.read = AsyncMock(side_effect=[stdout_data, b""])
    mock_process.communicate = AsyncMock(return_value=(stdout_data, b""))

    mocker.patch(
        "llm.antigravity_cli_client.asyncio.create_subprocess_exec",
        return_value=mock_process,
    )

    # 模擬 SQLite 對話資料庫
    db_file = tmp_path / "test-session-1234.db"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE steps (idx INTEGER, step_type INTEGER, step_payload BLOB);")
    
    # 插入一筆 AI 回覆 payload 模擬數據 (step_type = 15)
    sample_payload = b"bot-abc-123B \xe4\xbd\xa0\xe5\xa5\xbd\xef\xbc\x81\xe6\x88\x91\xe6\x98\xaf AI"
    cursor.execute("INSERT INTO steps VALUES (1, 15, ?);", (sample_payload,))
    conn.commit()
    conn.close()

    # Mock 使用者 Home 路徑中的 db 檔搜尋
    mocker.patch("llm.antigravity_cli_client.os.path.join", return_value=str(db_file))

    client = AntigravityCLIClient()
    
    results = []
    async for chunk in client.send_message("hi"):
        results.append(chunk)

    assert client.session_id == "test-session-1234"
    assert "你好！我是 AI" in results
