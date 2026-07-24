# ai_voice_assistant/tests/test_antigravity_cli.py
import asyncio
import json
import os
import subprocess
import sys
import threading
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from llm.antigravity_cli_client import AntigravityCLIClient, _looks_like_cli_error, _strip_ansi
from llm.base_client import LLMBackendUnavailableError, STREAM_ACTIVITY_KEEPALIVE


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


def test_build_command_args_does_not_auto_resume(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")

    client = AntigravityCLIClient()
    command = client._build_command_args("hello")

    assert client.session_id is None
    assert command[command.index("--add-dir") + 1] == client.project_dir
    assert "--conversation" not in command


def test_build_command_args_preserves_workspace_path_with_spaces(mocker, tmp_path):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")

    project_dir = tmp_path / "agent workspace"
    client = AntigravityCLIClient(project_dir=str(project_dir))
    command = client._build_command_args("hello")

    assert command[command.index("--add-dir") + 1] == client.project_dir


def test_build_command_args_keeps_quoted_prompt_in_one_argument(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")

    client = AntigravityCLIClient()
    command = client._build_command_args('hello "agy"')
    prompt = command[command.index("-p") + 1]

    assert "Runtime instruction for this agy --print call:" in prompt
    assert "Return only the final user-facing text" in prompt
    assert "User message:" in prompt
    assert 'hello "agy"' in prompt
    assert len(command) == 8


def test_build_command_args_includes_explicit_session_id(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")

    client = AntigravityCLIClient()
    command = client._build_command_args("hello", session_id="latest-session")

    assert command[command.index("--add-dir") + 1] == client.project_dir
    assert command[-2:] == ["--conversation", "latest-session"]
    assert "--new-project" not in command


def test_build_command_args_without_session_starts_fresh_conversation_in_project(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")

    client = AntigravityCLIClient()
    command = client._build_command_args("hello")

    assert command[command.index("--add-dir") + 1] == client.project_dir
    assert "--conversation" not in command
    assert "--continue" not in command
    assert "--new-project" not in command


def test_build_command_args_keeps_cli_like_text_inside_prompt(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")
    client = AntigravityCLIClient()

    command = client._build_command_args('probe " --version " tail')

    assert command[0] == "agy"
    assert command[command.index("-p") + 1].endswith(
        'User message:\nprobe " --version " tail'
    )
    assert command.count("--version") == 0


@pytest.mark.asyncio
async def test_send_message_serializes_overlapping_requests(mocker):
    client = AntigravityCLIClient()
    release_first = threading.Event()
    first_started = threading.Event()
    calls = []

    def run_pty(command, _request_state):
        calls.append(command)
        if len(calls) == 1:
            first_started.set()
            release_first.wait(timeout=1)
            return "first", 0
        return "second", 0

    mocker.patch.object(client, "_run_pty_blocking", side_effect=run_pty)
    mocker.patch.object(client, "_get_latest_conversation_id", return_value=None)
    mocker.patch.object(
        client,
        "_wait_for_new_conversation_id",
        new=AsyncMock(return_value=None),
    )

    async def collect(text):
        return [
            chunk
            async for chunk in client.send_message(text)
            if chunk != STREAM_ACTIVITY_KEEPALIVE
        ]

    first_task = asyncio.create_task(collect("one"))
    while not first_started.is_set():
        await asyncio.sleep(0.01)
    second_task = asyncio.create_task(collect("two"))
    await asyncio.sleep(0.05)

    assert len(calls) == 1

    release_first.set()
    first_result, second_result = await asyncio.gather(first_task, second_task)
    assert first_result == ["first"]
    assert second_result == ["second"]


def test_run_pty_blocking_terminates_process_cancelled_before_bind(mocker):
    client = AntigravityCLIClient()
    process = MagicMock()
    process.isalive.return_value = True
    process.exitstatus = None
    fake_pty_process = MagicMock()
    fake_pty_process.spawn.return_value = process
    mocker.patch.dict(
        sys.modules,
        {"winpty": types.SimpleNamespace(PtyProcess=fake_pty_process)},
    )
    request_state = {
        "cancel_event": threading.Event(),
        "process": None,
    }
    request_state["cancel_event"].set()
    client._active_request_state = request_state

    client._run_pty_blocking("agy test", request_state)

    process.terminate.assert_called()
    process.readline.assert_not_called()
    assert request_state["process"] is None
    assert client._pty_process is None


def test_run_pty_blocking_passes_argv_without_manual_quoting(mocker, tmp_path):
    from winpty import PtyProcess

    class FakePtyProcess:
        exitstatus = 0

        def isalive(self):
            return False

        def readline(self):
            return ""

    spawn = mocker.patch.object(PtyProcess, "spawn", return_value=FakePtyProcess())
    client = AntigravityCLIClient(project_dir=str(tmp_path))
    command = [
        r"C:\Program Files\agy\agy.exe",
        "--add-dir",
        str(tmp_path / "workspace with spaces"),
        "-p",
        'probe " --version " tail',
    ]

    assert client._run_pty_blocking(command) == ("", 0)
    spawn.assert_called_once_with(command, cwd=str(tmp_path))


def test_run_pty_blocking_round_trips_quoted_argument_through_real_winpty():
    value = 'probe " --version " tail'
    probe = (
        "import json, os, sys; "
        "from llm.antigravity_cli_client import AntigravityCLIClient, _strip_ansi; "
        "client = AntigravityCLIClient(project_dir=os.getcwd()); "
        f"value = {value!r}; "
        "raw, status = client._run_pty_blocking("
        "[sys.executable, '-c', 'import sys; print(sys.argv[1])', value]); "
        "print(json.dumps({'status': status, 'output': _strip_ansi(raw).strip()}))"
    )

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip())
    assert result == {"status": 0, "output": value}


def test_run_pty_blocking_terminates_and_raises_on_read_failure(mocker):
    from winpty import PtyProcess

    class BrokenReaderProcess:
        exitstatus = None

        def __init__(self):
            self.terminated = False

        def isalive(self):
            return not self.terminated

        def readline(self):
            raise RuntimeError("simulated PTY read failure")

        def terminate(self):
            self.terminated = True

    process = BrokenReaderProcess()
    mocker.patch.object(PtyProcess, "spawn", return_value=process)
    client = AntigravityCLIClient()

    with pytest.raises(RuntimeError, match="PTY output read failed"):
        client._run_pty_blocking(["agy", "-p", "hello"])

    assert process.terminated is True
    assert client._pty_process is None


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


def test_get_latest_conversation_id_retries_partial_cache_write(tmp_path, mocker):
    home = tmp_path / "home"
    project_dir = tmp_path / "agent_workspace"
    conv_dir = home / ".gemini" / "antigravity-cli" / "conversations"
    cache_dir = home / ".gemini" / "antigravity-cli" / "cache"
    conv_dir.mkdir(parents=True)
    cache_dir.mkdir(parents=True)
    project_dir.mkdir()

    conv_id = "518e8179-70ed-4c0d-947f-b337a27f8fff"
    (conv_dir / f"{conv_id}.db").write_text("conversation", encoding="utf-8")
    (cache_dir / "last_conversations.json").write_text("{}", encoding="utf-8")
    mocker.patch("llm.antigravity_cli_client.os.path.expanduser", return_value=str(home))
    json_load = mocker.patch(
        "llm.antigravity_cli_client.json.load",
        side_effect=[
            json.JSONDecodeError("partial write", "", 0),
            {str(project_dir): conv_id},
        ],
    )
    sleep = mocker.patch("llm.antigravity_cli_client.time.sleep")

    client = AntigravityCLIClient(project_dir=str(project_dir))

    assert client._get_latest_conversation_id() == conv_id
    assert json_load.call_count == 2
    sleep.assert_called_once()


@pytest.mark.asyncio
async def test_wait_for_new_conversation_id_rejects_preexisting_id(mocker):
    client = AntigravityCLIClient()
    get_latest = mocker.patch.object(
        client,
        "_get_latest_conversation_id",
        side_effect=["old-session", "old-session", "new-session"],
    )
    sleep = mocker.patch(
        "llm.antigravity_cli_client.asyncio.sleep",
        new=AsyncMock(),
    )

    assert await client._wait_for_new_conversation_id("old-session") == "new-session"
    assert get_latest.call_count == 3
    assert sleep.await_count == 2


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
    assert _looks_like_cli_error("Error: timeout waiting for response")


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
    run_pty = mocker.patch.object(
        AntigravityCLIClient,
        "_run_pty_blocking",
        return_value=(fake_raw, 0),
    )

    # 模擬自動偵測 latest conversation id
    mocker.patch.object(
        AntigravityCLIClient,
        "_get_latest_conversation_id",
        return_value="old-cached-uuid",
    )
    mocker.patch.object(
        AntigravityCLIClient,
        "_wait_for_new_conversation_id",
        new=AsyncMock(return_value="new-detected-uuid"),
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
    command = run_pty.call_args.args[0]
    assert command[command.index("--add-dir") + 1] == client.project_dir
    assert "--conversation" not in command
    assert "--continue" not in command
    assert "--new-project" not in command


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
async def test_send_message_does_not_apply_stale_incremental_output_to_fresh_session(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")
    mocker.patch.object(
        AntigravityCLIClient,
        "_run_pty_blocking",
        return_value=("FIRST\r\nSECOND\r\n", 0),
    )
    mocker.patch.object(
        AntigravityCLIClient,
        "_get_latest_conversation_id",
        return_value=None,
    )
    mocker.patch.object(
        AntigravityCLIClient,
        "_wait_for_new_conversation_id",
        new=AsyncMock(return_value="new-session"),
    )

    client = AntigravityCLIClient()
    client._last_cleaned_output = "FIRST"

    results = [
        chunk
        async for chunk in client.send_message("hello")
        if chunk != STREAM_ACTIVITY_KEEPALIVE
    ]

    assert results == ["FIRST\r\nSECOND"]
    assert client._last_cleaned_output == "FIRST\r\nSECOND"
    assert client.session_id == "new-session"


@pytest.mark.asyncio
async def test_send_message_preserves_repeated_identical_response_when_resuming(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")
    mocker.patch.object(
        AntigravityCLIClient,
        "_run_pty_blocking",
        return_value=("[HEARTBEAT_NOP]\r\n", 0),
    )
    mocker.patch.object(
        AntigravityCLIClient,
        "_get_latest_conversation_id",
        return_value="existing-session",
    )

    client = AntigravityCLIClient()
    client.session_id = "existing-session"
    client._last_cleaned_output = "[HEARTBEAT_NOP]"
    mocker.patch.object(client, "_conversation_exists", return_value=True)

    results = []
    async for chunk in client.send_message("heartbeat"):
        if chunk != STREAM_ACTIVITY_KEEPALIVE:
            results.append(chunk)

    assert results == ["[HEARTBEAT_NOP]"]
    assert client._last_cleaned_output == "[HEARTBEAT_NOP]"


@pytest.mark.asyncio
async def test_send_message_raises_on_internal_output_leak(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")
    mocker.patch.object(
        AntigravityCLIClient,
        "_run_pty_blocking",
        return_value=(
            "[2026-07-03T07:39:53+08:00] task-24 has started running.\r\n"
            "<thought\r\n"
            "secret internal reasoning\r\n"
            "Final answer.\r\n",
            0,
        ),
    )

    client = AntigravityCLIClient()
    client.session_id = "existing-session"
    client._last_cleaned_output = "Previous response"
    mocker.patch.object(client, "_conversation_exists", return_value=True)

    with pytest.raises(RuntimeError, match="internal output"):
        async for _chunk in client.send_message("weather"):
            pass

    assert client.session_id is None
    assert client._last_cleaned_output == ""


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
        return_value="old-cached-session",
    )
    mocker.patch.object(
        AntigravityCLIClient,
        "_wait_for_new_conversation_id",
        new=AsyncMock(return_value="new-session"),
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
    assert first_command[first_command.index("--add-dir") + 1] == client.project_dir
    assert second_command[second_command.index("--add-dir") + 1] == client.project_dir
    assert first_command[-2:] == ["--conversation", "old-session"]
    assert "--conversation" not in second_command
    assert "--continue" not in second_command
    assert "--new-project" not in second_command


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
async def test_send_message_preserves_cli_timeout_text_on_nonzero_exit(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")
    mocker.patch.object(
        AntigravityCLIClient,
        "_run_pty_blocking",
        return_value=("Error: timeout waiting for response\r\n", 1),
    )
    mocker.patch.object(
        AntigravityCLIClient,
        "_get_latest_conversation_id",
        return_value=None,
    )
    client = AntigravityCLIClient()

    with pytest.raises(
        LLMBackendUnavailableError,
        match="timeout waiting for response",
    ):
        async for _chunk in client.send_message("hello"):
            pass


@pytest.mark.asyncio
async def test_send_message_raises_when_cli_timeout_is_appended_to_response(mocker):
    mocker.patch("llm.antigravity_cli_client.shutil.which", return_value="agy")
    mocker.patch.object(
        AntigravityCLIClient,
        "_run_pty_blocking",
        return_value=(
            "Previous response\r\n"
            "I will check the file now.\r\n"
            "Error: timed out waiting for response\r\n",
            0,
        ),
    )

    client = AntigravityCLIClient()
    client.session_id = "existing-session"
    client._last_cleaned_output = "Previous response"
    mocker.patch.object(client, "_conversation_exists", return_value=True)

    with pytest.raises(RuntimeError, match="timed out waiting for response"):
        async for _chunk in client.send_message("hello"):
            pass

    assert client._last_cleaned_output == "Previous response"


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
