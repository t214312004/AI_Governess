import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, call
from llm.claude_code_client import ClaudeCodeClient
from llm.codex_cli_client import CodexCLIClient
from llm.opencode_cli_client import OpenCodeCLIClient
from llm.grok_cli_client import GrokCLIClient
from llm.antigravity_cli_client import AntigravityCLIClient
from llm.acp_stdio_client import ACPStdioClient, _ACPStreamContext
from llm.base_client import LLMBackendUnavailableError, STREAM_ACTIVITY_KEEPALIVE
from llm.client_factory import create_llm_client

@pytest.mark.asyncio
async def test_claude_client_success(mocker):
    mocker.patch("llm.claude_code_client.shutil.which", return_value="claude")
    client = ClaudeCodeClient()
    mock_process = MagicMock()
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = [
        b'',
        '{"type": "content_block_delta", "delta": {"type": "text_delta", "text": "你好"}}'.encode(),
        b'invalid json',
        '{"type": "content_block_delta", "delta": {"type": "text_delta", "text": "嗎"}}'.encode()
    ]
    mock_process.returncode = 0
    mock_process.kill = MagicMock()
    mock_process.wait = AsyncMock()
    mock_process.stderr.readline = AsyncMock(return_value=b"")
    mocker.patch("llm.claude_code_client.asyncio.create_subprocess_exec", return_value=mock_process)

    results = [chunk async for chunk in client.send_message("測試")]
    assert results == ["你好", "嗎"]

@pytest.mark.asyncio
async def test_claude_client_latest_stream_json_events(mocker):
    mocker.patch("llm.claude_code_client.shutil.which", return_value="claude")
    client = ClaudeCodeClient(project_dir=".")
    mock_process = MagicMock()
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "sess-1"}).encode(),
        json.dumps({
            "type": "stream_event",
            "session_id": "sess-1",
            "event": {"type": "content_block_start", "content_block": {"type": "tool_use"}},
        }).encode(),
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "你好"},
            },
        }).encode(),
    ]
    mock_process.returncode = 0
    mock_process.kill = MagicMock()
    mock_process.wait = AsyncMock()
    mock_process.stderr.readline = AsyncMock(return_value=b"")
    spawn = mocker.patch("llm.claude_code_client.asyncio.create_subprocess_exec", return_value=mock_process)

    results = [chunk async for chunk in client.send_message("測試")]

    assert results == [STREAM_ACTIVITY_KEEPALIVE, STREAM_ACTIVITY_KEEPALIVE, "你好"]
    assert client.session_id == "sess-1"
    cmd = spawn.call_args.args
    assert "--verbose" in cmd
    assert "--include-partial-messages" in cmd
    assert "--permission-mode" in cmd
    assert "--tools" in cmd

@pytest.mark.asyncio
async def test_claude_refresh_session_clears_runtime_session():
    client = ClaudeCodeClient(session_id="sess-1")

    refreshed = await client.refresh_session()

    assert refreshed is True
    assert client.session_id is None

@pytest.mark.asyncio
async def test_claude_client_cancel(mocker):
    client = ClaudeCodeClient()
    client.process = MagicMock()
    client.process.returncode = None
    client.process.kill = MagicMock()
    process = client.process
    await client.cancel()
    process.kill.assert_called_once()
    assert client.process is None

@pytest.mark.asyncio
async def test_claude_client_process_lookup_error(mocker):
    client = ClaudeCodeClient()
    client.process = MagicMock()
    client.process.returncode = None
    client.process.kill = MagicMock(side_effect=ProcessLookupError())
    await client.cancel()
    assert client.process is None

def _make_acp_mock_process(stdout_items):
    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.stdin = MagicMock()
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stderr = AsyncMock()
    mock_process.stderr.readline = AsyncMock(return_value=b"")
    mock_process.wait = AsyncMock(return_value=0)

    stdout_queue = asyncio.Queue()
    for item in stdout_items:
        if isinstance(item, str):
            item = item.encode("utf-8")
        stdout_queue.put_nowait(item)

    async def mock_readline():
        await asyncio.sleep(0.01)
        if stdout_queue.empty():
            return b""
        return await stdout_queue.get()

    mock_process.stdout.readline.side_effect = mock_readline
    return mock_process


def _written_acp_messages(mock_process):
    messages = []
    for write_call in mock_process.stdin.write.call_args_list:
        payload = write_call.args[0]
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        messages.append(json.loads(payload))
    return messages


def _make_opencode_workspace(tmp_path):
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text("memory", encoding="utf-8")
    return tmp_path


@pytest.mark.asyncio
async def test_opencode_client_success_streams_agent_message_chunks(mocker, tmp_path):
    mocker.patch("llm.acp_stdio_client.shutil.which", return_value="opencode.cmd")
    client = OpenCodeCLIClient(project_dir=str(_make_opencode_workspace(tmp_path)))
    mock_process = _make_acp_mock_process(
        [
            '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{"sessionCapabilities":{"resume":true}}}}\n',
            '{"jsonrpc":"2.0","id":2,"result":{"sessionId":"oc-1"}}\n',
            '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"oc-1","update":{"sessionUpdate":"agent_message_chunk","content":{"text":"Hello "}}}}\n',
            '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"oc-1","update":{"sessionUpdate":"agent_message_chunk","content":{"text":"world"}}}}\n',
            '{"jsonrpc":"2.0","id":3,"result":{"stopReason":"end_turn"}}\n',
            b"",
        ]
    )
    mocker.patch("llm.acp_stdio_client.asyncio.create_subprocess_exec", return_value=mock_process)

    results = [chunk async for chunk in client.send_message("hi")]

    assert results == ["Hello ", "world"]
    assert client.session_id == "oc-1"


@pytest.mark.asyncio
async def test_opencode_client_ignores_thought_and_usage_updates(mocker, tmp_path):
    mocker.patch("llm.acp_stdio_client.shutil.which", return_value="opencode.cmd")
    client = OpenCodeCLIClient(project_dir=str(_make_opencode_workspace(tmp_path)))
    mock_process = _make_acp_mock_process(
        [
            '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{}}}\n',
            '{"jsonrpc":"2.0","id":2,"result":{"sessionId":"oc-1"}}\n',
            '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"oc-1","update":{"sessionUpdate":"agent_thought_chunk","content":{"text":"secret thought"}}}}\n',
            '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"oc-1","update":{"sessionUpdate":"usage_update","tokens":10}}}\n',
            '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"oc-1","update":{"sessionUpdate":"agent_message_chunk","content":{"text":"done"}}}}\n',
            '{"jsonrpc":"2.0","id":3,"result":{"stopReason":"end_turn"}}\n',
            b"",
        ]
    )
    mocker.patch("llm.acp_stdio_client.asyncio.create_subprocess_exec", return_value=mock_process)

    results = [chunk async for chunk in client.send_message("hi")]

    assert results == [STREAM_ACTIVITY_KEEPALIVE, "done"]


@pytest.mark.asyncio
async def test_opencode_client_tool_update_keepalive(mocker, tmp_path):
    mocker.patch("llm.acp_stdio_client.shutil.which", return_value="opencode.cmd")
    client = OpenCodeCLIClient(project_dir=str(_make_opencode_workspace(tmp_path)))
    mock_process = _make_acp_mock_process(
        [
            '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{}}}\n',
            '{"jsonrpc":"2.0","id":2,"result":{"sessionId":"oc-1"}}\n',
            '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"oc-1","update":{"sessionUpdate":"tool_call","toolCallId":"t1","title":"shell"}}}\n',
            '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"oc-1","update":{"sessionUpdate":"tool_call_update","toolCallId":"t1","status":"completed","title":"shell"}}}\n',
            '{"jsonrpc":"2.0","id":3,"result":{"stopReason":"end_turn"}}\n',
            b"",
        ]
    )
    mocker.patch("llm.acp_stdio_client.asyncio.create_subprocess_exec", return_value=mock_process)

    results = [chunk async for chunk in client.send_message("hi")]

    assert results == [STREAM_ACTIVITY_KEEPALIVE, STREAM_ACTIVITY_KEEPALIVE]


@pytest.mark.asyncio
async def test_opencode_prompt_pending_emits_periodic_keepalive(mocker, tmp_path):
    mocker.patch("llm.acp_stdio_client.shutil.which", return_value="opencode.cmd")
    mocker.patch("llm.acp_stdio_client._PROMPT_KEEPALIVE_INTERVAL_SECONDS", 0.001)
    client = OpenCodeCLIClient(project_dir=str(_make_opencode_workspace(tmp_path)))
    
    # 建立 mock_process 並將 readline 延遲拉大以克服 Windows 系統 Timer 精確度限制
    mock_process = _make_acp_mock_process(
        [
            '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{}}}\n',
            '{"jsonrpc":"2.0","id":2,"result":{"sessionId":"oc-1"}}\n',
            '{"jsonrpc":"2.0","id":3,"result":{"stopReason":"end_turn"}}\n',
            b"",
        ]
    )
    
    stdout_queue = asyncio.Queue()
    for item in [
        '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{}}}\n',
        '{"jsonrpc":"2.0","id":2,"result":{"sessionId":"oc-1"}}\n',
        '{"jsonrpc":"2.0","id":3,"result":{"stopReason":"end_turn"}}\n',
        b"",
    ]:
        if isinstance(item, str):
            item = item.encode("utf-8")
        stdout_queue.put_nowait(item)

    async def mock_readline_slow():
        await asyncio.sleep(0.1)  # 遠大於 Windows 的 15.6ms 限制
        if stdout_queue.empty():
            return b""
        return await stdout_queue.get()

    mock_process.stdout.readline.side_effect = mock_readline_slow
    mocker.patch("llm.acp_stdio_client.asyncio.create_subprocess_exec", return_value=mock_process)

    results = [chunk async for chunk in client.send_message("hi")]

    assert STREAM_ACTIVITY_KEEPALIVE in results


@pytest.mark.asyncio
async def test_opencode_permission_request_selects_allow_option():
    client = OpenCodeCLIClient(project_dir=".")
    client.process = MagicMock()
    client.process.stdin = MagicMock()
    client.process.stdin.write = MagicMock()
    client.process.stdin.drain = AsyncMock()

    await client._handle_server_request(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "session/request_permission",
            "params": {
                "options": [
                    {"optionId": "reject", "kind": "reject"},
                    {"optionId": "allow-session", "kind": "allow_always"},
                ]
            },
        }
    )

    response = json.loads(client.process.stdin.write.call_args.args[0].decode("utf-8"))
    assert response["result"]["outcome"] == {
        "outcome": "selected",
        "optionId": "allow-session",
    }


@pytest.mark.asyncio
async def test_opencode_permission_request_returns_cancelled_after_cancel():
    client = OpenCodeCLIClient(project_dir=".")
    client._cancel_flag = True
    client.process = MagicMock()
    client.process.stdin = MagicMock()
    client.process.stdin.write = MagicMock()
    client.process.stdin.drain = AsyncMock()

    await client._handle_server_request(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "session/request_permission",
            "params": {"options": [{"optionId": "allow-session", "kind": "allow_always"}]},
        }
    )

    response = json.loads(client.process.stdin.write.call_args.args[0].decode("utf-8"))
    assert response["result"]["outcome"] == {"outcome": "cancelled"}


@pytest.mark.asyncio
async def test_opencode_set_model_uses_session_config_option(mocker, tmp_path):
    mocker.patch("llm.acp_stdio_client.shutil.which", return_value="opencode.cmd")
    client = OpenCodeCLIClient(
        project_dir=str(_make_opencode_workspace(tmp_path)),
        model="model-a",
    )
    mock_process = _make_acp_mock_process(
        [
            '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{}}}\n',
            '{"jsonrpc":"2.0","id":2,"result":{"sessionId":"oc-1","configOptions":[{"id":"model","options":[{"value":"model-a"},{"value":"model-b"}]}]}}\n',
            '{"jsonrpc":"2.0","id":3,"result":{}}\n',
            b"",
        ]
    )
    mocker.patch("llm.acp_stdio_client.asyncio.create_subprocess_exec", return_value=mock_process)

    assert await client.ensure_ready() is True

    messages = _written_acp_messages(mock_process)
    assert any(
        message["method"] == "session/set_config_option"
        and message["params"]["configId"] == "model"
        and message["params"]["value"] == "model-a"
        for message in messages
    )


@pytest.mark.asyncio
async def test_opencode_empty_model_and_mode_use_defaults(mocker, tmp_path):
    mocker.patch("llm.acp_stdio_client.shutil.which", return_value="opencode.cmd")
    client = OpenCodeCLIClient(project_dir=str(_make_opencode_workspace(tmp_path)), model="", mode="")
    mock_process = _make_acp_mock_process(
        [
            '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{}}}\n',
            '{"jsonrpc":"2.0","id":2,"result":{"sessionId":"oc-1"}}\n',
            b"",
        ]
    )
    mocker.patch("llm.acp_stdio_client.asyncio.create_subprocess_exec", return_value=mock_process)

    assert await client.ensure_ready() is True

    methods = [message["method"] for message in _written_acp_messages(mock_process)]
    assert "session/set_config_option" not in methods


@pytest.mark.asyncio
async def test_opencode_invalid_model_is_rejected_before_set_config(mocker, tmp_path):
    mocker.patch("llm.acp_stdio_client.shutil.which", return_value="opencode.cmd")
    client = OpenCodeCLIClient(
        project_dir=str(_make_opencode_workspace(tmp_path)),
        model="missing-model",
    )
    mock_process = _make_acp_mock_process(
        [
            '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{}}}\n',
            '{"jsonrpc":"2.0","id":2,"result":{"sessionId":"oc-1","configOptions":[{"id":"model","options":[{"value":"model-a"}]}]}}\n',
            b"",
        ]
    )
    mocker.patch("llm.acp_stdio_client.asyncio.create_subprocess_exec", return_value=mock_process)

    with pytest.raises(RuntimeError, match="missing-model"):
        await client.ensure_ready()

    methods = [message["method"] for message in _written_acp_messages(mock_process)]
    assert "session/set_config_option" not in methods


def test_opencode_runtime_config_preloads_memory(tmp_path):
    workspace = _make_opencode_workspace(tmp_path)
    client = OpenCodeCLIClient(project_dir=str(workspace))

    client._before_start()
    env = client._build_subprocess_env()
    runtime_config = json.loads(env["OPENCODE_CONFIG_CONTENT"])

    assert runtime_config["permission"] == "allow"
    assert runtime_config["instructions"] == [
        str((workspace / "MEMORY.md").resolve()).replace("\\", "/")
    ]
    assert "AGENTS.md" not in " ".join(runtime_config["instructions"])
    assert "OPENCODE_ENABLE_EXA" not in env


def test_opencode_web_search_enables_exa_env(tmp_path):
    workspace = _make_opencode_workspace(tmp_path)
    client = OpenCodeCLIClient(project_dir=str(workspace), enable_web_search=True)

    client._before_start()
    env = client._build_subprocess_env()

    assert env["OPENCODE_ENABLE_EXA"] == "1"


def test_opencode_context_preload_missing_required_file_fails_closed(mocker, tmp_path):
    log_event_mock = mocker.patch("llm.opencode_cli_client.log_event")
    client = OpenCodeCLIClient(
        project_dir=str(tmp_path),
        required_context_files=["MISSING_AGENTS.md"],
        instruction_files=["MISSING_MEMORY.md"],
    )

    with pytest.raises(LLMBackendUnavailableError, match="MISSING_AGENTS.md"):
        client._before_start()

    events = [call.args[2] for call in log_event_mock.call_args_list]
    assert "opencode.required_context_file" in events
    assert "opencode.instruction_file" in events


@pytest.mark.asyncio
async def test_acp_refresh_invalid_response_restores_ready_session(tmp_path):
    client = OpenCodeCLIClient(project_dir=str(_make_opencode_workspace(tmp_path)))
    client.process = MagicMock(returncode=None)
    client.session_id = "old-session"
    client._ready_event.set()
    client._send_request = AsyncMock(return_value={"result": {}})

    assert await client.refresh_session() is False
    assert client.session_id == "old-session"
    assert client._ready_event.is_set()


@pytest.mark.asyncio
async def test_acp_receive_loop_discards_unknown_late_response(tmp_path):
    client = OpenCodeCLIClient(project_dir=str(_make_opencode_workspace(tmp_path)))
    client.process = MagicMock(returncode=None)
    client.process.stdout = AsyncMock()
    client.process.stdout.readline = AsyncMock(
        side_effect=[b'{"jsonrpc":"2.0","id":999,"result":{}}\n', b""]
    )

    await client._receive_loop()

    assert client._response_futures == {}
    assert not hasattr(client, "_buffered_responses")


@pytest.mark.asyncio
async def test_acp_start_skips_duplicate_spawn_when_ready(mocker, tmp_path):
    client = OpenCodeCLIClient(project_dir=str(_make_opencode_workspace(tmp_path)))
    client.process = MagicMock(returncode=None)
    client._ready_event.set()
    spawn = mocker.patch(
        "llm.acp_stdio_client.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
    )

    await client._start_acp()

    spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_acp_receive_loop_fails_pending_requests_when_process_exits(tmp_path):
    client = OpenCodeCLIClient(project_dir=str(_make_opencode_workspace(tmp_path)))
    client.process = MagicMock(returncode=1)
    pending = asyncio.get_running_loop().create_future()
    client._response_futures[999] = pending

    await client._receive_loop()

    with pytest.raises(RuntimeError, match="terminated unexpectedly"):
        await pending


def test_acp_stream_context_skips_duplicate_chunks():
    stream_context = _ACPStreamContext()

    ACPStdioClient._enqueue_stream_chunk(stream_context, "hello")
    ACPStdioClient._enqueue_stream_chunk(stream_context, "hello")

    assert stream_context.queue.get_nowait() == "hello"
    assert stream_context.queue.empty()
    assert stream_context.emitted_text == "hello"


def test_acp_stream_context_replay_boundary_emits_only_suffix():
    stream_context = _ACPStreamContext()

    ACPStdioClient._enqueue_stream_chunk(stream_context, "hello")
    ACPStdioClient._mark_stream_replay_boundary(stream_context)
    ACPStdioClient._enqueue_stream_chunk(stream_context, "hello world")

    assert stream_context.queue.get_nowait() == "hello"
    assert stream_context.queue.get_nowait() == " world"
    assert stream_context.queue.empty()
    assert stream_context.emitted_text == "hello world"


@pytest.mark.asyncio
async def test_acp_close_logs_background_task_failures_without_raising(mocker, tmp_path):
    client = OpenCodeCLIClient(project_dir=str(_make_opencode_workspace(tmp_path)))
    client.process = MagicMock(returncode=None)
    client.process.wait = AsyncMock(return_value=0)
    log_event = mocker.patch("llm.acp_stdio_client.log_event")

    async def failing_task():
        raise RuntimeError("boom")

    client._receive_task = asyncio.create_task(failing_task())
    client._stderr_task = asyncio.create_task(asyncio.sleep(0))
    await asyncio.sleep(0)

    await client.aclose()

    events = [event.args[2] for event in log_event.call_args_list]
    assert "acp.shutdown_task_failed" in events
    assert client.process is None


@pytest.mark.asyncio
async def test_opencode_cancel_sends_session_cancel_and_best_effort_request_cancel(mocker):
    client = OpenCodeCLIClient(project_dir=".")
    client.process = MagicMock(returncode=None)
    client.session_id = "oc-1"
    client._ready_event.set()
    client._active_prompt_req_id = 33
    mock_send = mocker.patch.object(
        client,
        "_send_notification",
        new_callable=AsyncMock,
        side_effect=[None, RuntimeError("ignored")],
    )

    await client.cancel()

    mock_send.assert_has_awaits(
        [
            call("session/cancel", {"sessionId": "oc-1"}),
            call("$/cancelRequest", {"requestId": 33}),
        ]
    )


@pytest.mark.asyncio
async def test_opencode_refresh_session_creates_new_session_without_restart(mocker):
    client = OpenCodeCLIClient(project_dir=".")
    client.process = MagicMock(returncode=None)
    client.session_id = "old"
    client._ready_event.set()
    client._agent_capabilities = {"sessionCapabilities": {"close": True}}

    async def fake_send(method, params, timeout=None):
        if method == "session/new":
            return {"result": {"sessionId": "new"}}
        if method == "session/close":
            return {"result": {}}
        raise AssertionError(method)

    mock_send = mocker.patch.object(client, "_send_request", side_effect=fake_send)

    assert await client.refresh_session() is True
    assert client.session_id == "new"
    assert mock_send.await_count == 2


@pytest.mark.asyncio
async def test_opencode_resume_preferred_over_load(mocker, tmp_path):
    mocker.patch("llm.acp_stdio_client.shutil.which", return_value="opencode.cmd")
    client = OpenCodeCLIClient(
        project_dir=str(_make_opencode_workspace(tmp_path)),
        session_id="existing",
    )
    mock_process = _make_acp_mock_process(
        [
            '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{"sessionCapabilities":{"resume":true},"loadSession":true}}}\n',
            '{"jsonrpc":"2.0","id":2,"result":{}}\n',
            b"",
        ]
    )
    mocker.patch("llm.acp_stdio_client.asyncio.create_subprocess_exec", return_value=mock_process)

    assert await client.ensure_ready() is True

    methods = [message["method"] for message in _written_acp_messages(mock_process)]
    assert "session/resume" in methods
    assert "session/load" not in methods
    assert client.session_id == "existing"


@pytest.mark.asyncio
async def test_opencode_load_null_result_keeps_existing_session(mocker, tmp_path):
    mocker.patch("llm.acp_stdio_client.shutil.which", return_value="opencode.cmd")
    client = OpenCodeCLIClient(
        project_dir=str(_make_opencode_workspace(tmp_path)),
        session_id="existing",
    )
    mock_process = _make_acp_mock_process(
        [
            '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"agentCapabilities":{"loadSession":true}}}\n',
            '{"jsonrpc":"2.0","id":2,"result":null}\n',
            b"",
        ]
    )
    mocker.patch("llm.acp_stdio_client.asyncio.create_subprocess_exec", return_value=mock_process)

    assert await client.ensure_ready() is True
    assert client.session_id == "existing"


@pytest.mark.asyncio
async def test_opencode_ensure_ready_reports_startup_failures(mocker, tmp_path):
    mocker.patch("llm.acp_stdio_client.shutil.which", return_value="opencode.cmd")
    client = OpenCodeCLIClient(project_dir=str(_make_opencode_workspace(tmp_path)))
    mock_process = _make_acp_mock_process(
        [
            '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":99,"agentCapabilities":{}}}\n',
            b"",
        ]
    )
    mocker.patch("llm.acp_stdio_client.asyncio.create_subprocess_exec", return_value=mock_process)

    with pytest.raises(RuntimeError, match="protocol version"):
        await client.ensure_ready()


@pytest.mark.asyncio
async def test_acp_logging_redacts_raw_payloads(mocker):
    client = OpenCodeCLIClient(project_dir=".")
    client.session_id = "oc-1"
    client.process = MagicMock()
    client.process.stdin = MagicMock()
    client.process.stdin.write = MagicMock()
    client.process.stdin.drain = AsyncMock()
    log_event_mock = mocker.patch("llm.acp_stdio_client.log_event")

    await client._handle_server_request(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "session/request_permission",
            "params": {
                "toolCall": {
                    "rawInput": "PRIVATE_MEMORY_SENTINEL",
                    "rawOutput": "PRIVATE_TOOL_OUTPUT",
                },
                "options": [{"optionId": "allow", "kind": "allow_once"}],
            },
        }
    )

    rendered_calls = "\n".join(str(log_call) for log_call in log_event_mock.call_args_list)
    assert "PRIVATE_MEMORY_SENTINEL" not in rendered_calls
    assert "PRIVATE_TOOL_OUTPUT" not in rendered_calls


def test_opencode_template_bootstrap_creates_missing_private_workspace_files(tmp_path):
    client = OpenCodeCLIClient(project_dir=str(tmp_path))

    client._before_start()

    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "MEMORY.md").exists()

    original = "custom private rules"
    (tmp_path / "AGENTS.md").write_text(original, encoding="utf-8")
    client._before_start()
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_codex_client_success_filters_commentary(mocker):
    mocker.patch("llm.codex_cli_client.shutil.which", return_value="codex")
    client = CodexCLIClient()

    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.stdin = MagicMock()
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stderr = AsyncMock()
    mock_process.wait = AsyncMock(return_value=0)

    stdout_queue = asyncio.Queue()
    for item in [
        b'{"jsonrpc":"2.0","id":1,"result":{"codexHome":"C:/Users/test/.codex","platformFamily":"windows","platformOs":"windows","userAgent":"codex-cli"}}\n',
        b'{"jsonrpc":"2.0","id":2,"result":{"account":{"type":"chatgpt","email":"test@example.com","planType":"plus"},"requiresOpenaiAuth":true}}\n',
        b'{"jsonrpc":"2.0","id":3,"result":{"data":[{"id":"gpt-5.4","model":"gpt-5.4","isDefault":true,"hidden":false}]}}\n',
        b'{"jsonrpc":"2.0","id":4,"result":{"thread":{"id":"thread-1"},"model":"gpt-5.4","approvalPolicy":"never","approvalsReviewer":"user","cwd":"C:/tmp","modelProvider":"openai","sandbox":{"type":"dangerFullAccess"}}}\n',
        b'{"jsonrpc":"2.0","method":"turn/started","params":{"threadId":"thread-1","turn":{"id":"turn-1","status":"inProgress","items":[]}}}\n',
        b'{"jsonrpc":"2.0","method":"item/started","params":{"threadId":"thread-1","turnId":"turn-1","item":{"id":"item-commentary","type":"agentMessage","text":"","phase":"commentary"}}}\n',
        '{"jsonrpc":"2.0","method":"item/agentMessage/delta","params":{"threadId":"thread-1","turnId":"turn-1","itemId":"item-commentary","delta":"先幫你看一下"}}\n'.encode(),
        b'{"jsonrpc":"2.0","method":"item/started","params":{"threadId":"thread-1","turnId":"turn-1","item":{"id":"item-final","type":"agentMessage","text":"","phase":"final_answer"}}}\n',
        '{"jsonrpc":"2.0","method":"item/agentMessage/delta","params":{"threadId":"thread-1","turnId":"turn-1","itemId":"item-final","delta":"你好"}}\n'.encode(),
        '{"jsonrpc":"2.0","method":"item/agentMessage/delta","params":{"threadId":"thread-1","turnId":"turn-1","itemId":"item-final","delta":"嗎"}}\n'.encode(),
        b'{"jsonrpc":"2.0","method":"turn/completed","params":{"threadId":"thread-1","turn":{"id":"turn-1","status":"completed","items":[]}}}\n',
        b'{"jsonrpc":"2.0","id":5,"result":{"turn":{"id":"turn-1","status":"inProgress","items":[]}}}\n',
        b"",
    ]:
        stdout_queue.put_nowait(item)

    async def mock_stdout_readline():
        await asyncio.sleep(0.01)
        if stdout_queue.empty():
            return b""
        return await stdout_queue.get()

    mock_process.stdout.readline.side_effect = mock_stdout_readline
    mock_process.stderr.readline = AsyncMock(return_value=b"")
    mocker.patch("llm.codex_cli_client.asyncio.create_subprocess_exec", return_value=mock_process)

    results = [chunk async for chunk in client.send_message("測試")]

    assert results == ["你好", "嗎"]
    assert client.thread_id == "thread-1"
    assert client.model == "gpt-5.4"

@pytest.mark.asyncio
async def test_codex_client_requires_login_raises_typed_error(mocker):
    mocker.patch("llm.codex_cli_client.shutil.which", return_value="codex")
    client = CodexCLIClient()

    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.stdin = MagicMock()
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stderr = AsyncMock()

    stdout_queue = asyncio.Queue()
    for item in [
        b'{"jsonrpc":"2.0","id":1,"result":{"codexHome":"C:/Users/test/.codex","platformFamily":"windows","platformOs":"windows","userAgent":"codex-cli"}}\n',
        b'{"jsonrpc":"2.0","id":2,"result":{"account":null,"requiresOpenaiAuth":true}}\n',
        b"",
    ]:
        stdout_queue.put_nowait(item)

    async def mock_stdout_readline():
        await asyncio.sleep(0.01)
        if stdout_queue.empty():
            return b""
        return await stdout_queue.get()

    mock_process.stdout.readline.side_effect = mock_stdout_readline
    mock_process.stderr.readline = AsyncMock(return_value=b"")
    mocker.patch("llm.codex_cli_client.asyncio.create_subprocess_exec", return_value=mock_process)

    with pytest.raises(LLMBackendUnavailableError, match="Codex CLI 尚未登入"):
        _ = [chunk async for chunk in client.send_message("測試")]

@pytest.mark.asyncio
async def test_codex_start_server_falls_back_to_thread_start_when_resume_fails(mocker):
    mocker.patch("llm.codex_cli_client.shutil.which", return_value="codex")
    client = CodexCLIClient(thread_id="stale-thread")

    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.stdin = MagicMock()
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stderr = AsyncMock()

    stdout_queue = asyncio.Queue()
    for item in [
        b'{"jsonrpc":"2.0","id":1,"result":{"codexHome":"C:/Users/test/.codex","platformFamily":"windows","platformOs":"windows","userAgent":"codex-cli"}}\n',
        b'{"jsonrpc":"2.0","id":2,"result":{"account":{"type":"chatgpt","email":"test@example.com","planType":"plus"},"requiresOpenaiAuth":false}}\n',
        b'{"jsonrpc":"2.0","id":3,"result":{"data":[{"id":"gpt-5.4","model":"gpt-5.4","isDefault":true,"hidden":false}]}}\n',
        b'{"jsonrpc":"2.0","id":4,"error":{"message":"stale thread"}}\n',
        b'{"jsonrpc":"2.0","id":5,"result":{"thread":{"id":"fresh-thread"},"model":"gpt-5.4","approvalPolicy":"never","approvalsReviewer":"user","cwd":"C:/tmp","modelProvider":"openai","sandbox":{"type":"dangerFullAccess"}}}\n',
        b"",
    ]:
        stdout_queue.put_nowait(item)

    async def mock_stdout_readline():
        await asyncio.sleep(0.01)
        if stdout_queue.empty():
            return b""
        return await stdout_queue.get()

    mock_process.stdout.readline.side_effect = mock_stdout_readline
    mock_process.stderr.readline = AsyncMock(return_value=b"")
    mocker.patch("llm.codex_cli_client.asyncio.create_subprocess_exec", return_value=mock_process)

    await client._start_server()

    assert client.thread_id == "fresh-thread"
    assert client._ready_event.is_set()

@pytest.mark.asyncio
async def test_codex_client_cancel_sends_turn_interrupt(mocker):
    client = CodexCLIClient(thread_id="thread-1")
    client._active_turn_id = "turn-1"

    mock_send = mocker.patch.object(client, "_send_request", new_callable=AsyncMock, return_value={"result": {}})

    await client.cancel()

    assert client._cancel_flag is True
    mock_send.assert_awaited_once_with(
        "turn/interrupt",
        {"threadId": "thread-1", "turnId": "turn-1"},
    )

@pytest.mark.asyncio
async def test_codex_refresh_session_creates_new_thread_without_restarting_process(mocker):
    client = CodexCLIClient(thread_id="thread-old")
    client.process = MagicMock()
    client.process.returncode = None

    async def fake_start_thread():
        client.thread_id = "thread-new"

    mock_start_thread = mocker.patch.object(client, "_start_thread", side_effect=fake_start_thread)

    refreshed = await client.refresh_session()

    mock_start_thread.assert_awaited_once()
    assert refreshed is True
    assert client.thread_id == "thread-new"


@pytest.mark.asyncio
async def test_codex_send_message_waits_for_refresh_session_before_turn_start(mocker):
    client = CodexCLIClient(thread_id="thread-old")
    client.process = MagicMock()
    client.process.returncode = None
    client._ready_event.set()

    refresh_started = asyncio.Event()
    allow_refresh_finish = asyncio.Event()

    async def fake_start_thread():
        assert client.thread_id is None
        refresh_started.set()
        await allow_refresh_finish.wait()
        client.thread_id = "thread-new"

    send_calls = []

    async def fake_send_request(method, params):
        send_calls.append((method, dict(params)))
        return {"result": {"turn": {"id": "turn-1"}}}

    mocker.patch.object(client, "_start_thread", side_effect=fake_start_thread)
    mocker.patch.object(client, "_send_request", side_effect=fake_send_request)

    async def collect_response():
        return [chunk async for chunk in client.send_message("hello")]

    refresh_task = asyncio.create_task(client.refresh_session())
    await asyncio.wait_for(refresh_started.wait(), timeout=1.0)

    response_task = asyncio.create_task(collect_response())
    await asyncio.sleep(0.01)

    assert send_calls == []
    assert not response_task.done()

    allow_refresh_finish.set()
    assert await asyncio.wait_for(refresh_task, timeout=1.0) is True

    for _ in range(100):
        if "turn-1" in client._turn_states:
            break
        await asyncio.sleep(0.01)

    assert send_calls == [
        (
            "turn/start",
            {
                "threadId": "thread-new",
                "input": [{"type": "text", "text": "hello"}],
                "cwd": client.project_dir,
                "model": client.model,
                "effort": client.reasoning_effort,
                "personality": client.personality,
                "approvalPolicy": client.approval_policy,
                "sandboxPolicy": client._build_turn_sandbox_policy(),
            },
        )
    ]

    turn_state = client._turn_states["turn-1"]
    turn_state.queue.put_nowait("ready")
    turn_state.done.set()

    assert await asyncio.wait_for(response_task, timeout=1.0) == ["ready"]


@pytest.mark.asyncio
async def test_codex_refresh_session_starts_server_with_new_thread_when_process_missing(mocker):
    client = CodexCLIClient(thread_id="thread-old")

    async def fake_start_server():
        assert client.thread_id is None
        client.process = MagicMock()
        client.process.returncode = None
        client.thread_id = "thread-new"

    mock_start_server = mocker.patch.object(client, "_start_server", side_effect=fake_start_server)

    refreshed = await client.refresh_session()

    mock_start_server.assert_awaited_once()
    assert refreshed is True
    assert client.thread_id == "thread-new"


@pytest.mark.asyncio
async def test_codex_ensure_ready_starts_server(mocker):
    client = CodexCLIClient()

    async def fake_start_server():
        client.process = MagicMock()
        client.process.returncode = None
        client.thread_id = "thread-new"
        client._ready_event.set()

    mock_start_server = mocker.patch.object(client, "_start_server", side_effect=fake_start_server)

    assert await client.ensure_ready() is True
    mock_start_server.assert_awaited_once()
    assert client.thread_id == "thread-new"


@pytest.mark.asyncio
async def test_codex_ensure_ready_raises_when_login_required(mocker):
    client = CodexCLIClient()

    async def fake_start_server():
        client.process = MagicMock()
        client.process.returncode = None
        client._auth_unavailable_message = "login required"
        client._ready_event.set()

    mocker.patch.object(client, "_start_server", side_effect=fake_start_server)

    with pytest.raises(LLMBackendUnavailableError, match="login required"):
        await client.ensure_ready()


@pytest.mark.asyncio
async def test_codex_ensure_ready_reports_missing_executable(mocker):
    client = CodexCLIClient(request_timeout_seconds=1)
    mocker.patch(
        "llm.codex_cli_client.asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError("codex missing"),
    )

    with pytest.raises(LLMBackendUnavailableError, match="Codex"):
        await client.ensure_ready()


def test_codex_invalid_timeout_uses_safe_defaults():
    invalid = CodexCLIClient(request_timeout_seconds="not-a-number")
    infinite = CodexCLIClient(request_timeout_seconds=float("inf"))

    assert invalid.request_timeout_seconds == 30.0
    assert infinite.request_timeout_seconds == 30.0


@pytest.mark.asyncio
async def test_codex_process_logs_redact_raw_output(mocker):
    client = CodexCLIClient()
    client.process = MagicMock(returncode=None)
    client.process.stderr = AsyncMock()
    client.process.stderr.readline = AsyncMock(
        side_effect=["private stderr".encode() + b"\n", b""]
    )
    log_event = mocker.patch("llm.codex_cli_client.log_event")

    await client._stderr_loop()

    stderr_call = next(call for call in log_event.call_args_list if call.args[2] == "codex.stderr")
    assert stderr_call.kwargs["chars"] == len("private stderr")
    assert "detail" not in stderr_call.kwargs


@pytest.mark.asyncio
async def test_codex_noncompleted_turn_status_is_an_error():
    client = CodexCLIClient()
    state = client._get_turn_state("turn-aborted")

    await client._handle_notification(
        "turn/completed",
        {"turn": {"id": "turn-aborted", "status": "cancelled"}},
    )

    assert isinstance(state.error, RuntimeError)
    assert "cancelled" in str(state.error)


@pytest.mark.asyncio
async def test_acp_send_message_converts_startup_failure_to_typed_error(mocker, tmp_path):
    client = OpenCodeCLIClient(project_dir=str(_make_opencode_workspace(tmp_path)))
    mocker.patch.object(client, "ensure_ready", side_effect=RuntimeError("not installed"))

    with pytest.raises(LLMBackendUnavailableError, match="OpenCode CLI backend 尚未就緒"):
        _ = [chunk async for chunk in client.send_message("測試")]


def test_opencode_serialized_false_flags_remain_disabled(tmp_path):
    client = OpenCodeCLIClient(
        project_dir=str(_make_opencode_workspace(tmp_path)),
        auto_approve="false",
        use_runtime_config_content="false",
        enable_web_search="false",
    )

    assert client.auto_approve is False
    assert client.use_runtime_config_content is False
    assert client.enable_web_search is False



def test_client_factory():
    client1 = create_llm_client("claude_code", model="opus")
    assert isinstance(client1, ClaudeCodeClient)
    assert client1.model == "opus"
    assert client1.project_dir.endswith("agent_workspace")

    client2 = create_llm_client("codex_cli", project_dir="/tmp")
    assert isinstance(client2, CodexCLIClient)
    assert client2.sandbox == "workspace-write"
    assert client2.approval_policy == "on-request"

    client3 = create_llm_client(
        "opencode_cli",
        project_dir="/tmp",
        model="",
        mode="",
        enable_web_search=True,
    )
    assert isinstance(client3, OpenCodeCLIClient)
    assert client3.model is None
    assert client3.mode is None
    assert client3.enable_web_search is True

    client4 = create_llm_client("grok_cli", project_dir="/tmp", model="")
    assert isinstance(client4, GrokCLIClient)
    assert client4.model is None
    assert client4.auto_approve_scope == "once"

    client5 = create_llm_client("antigravity_cli", project_dir="/tmp")
    assert isinstance(client5, AntigravityCLIClient)
    assert client5.session_id is None

    with pytest.raises(ValueError, match="未知"):
        create_llm_client("unknown")


def test_client_factory_ignores_runtime_session_state():
    codex = create_llm_client("codex_cli", project_dir="/tmp", thread_id="stale-thread")
    opencode = create_llm_client("opencode_cli", project_dir="/tmp", session_id="stale-session")
    grok = create_llm_client("grok_cli", project_dir="/tmp", session_id="stale-session")
    antigravity = create_llm_client("antigravity_cli", project_dir="/tmp", session_id="stale-session")

    assert codex.thread_id is None
    assert opencode.session_id is None
    assert grok.session_id is None
    assert antigravity.session_id is None

