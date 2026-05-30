import asyncio
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, call
import httpx
from httpx_sse import ServerSentEvent
from llm.openclaw_client import OpenClawClient
from llm.claude_code_client import ClaudeCodeClient
from llm.codex_cli_client import CodexCLIClient
from llm.gemini_cli_client import GeminiCLIClient, _GeminiStreamContext
from llm.opencode_cli_client import OpenCodeCLIClient
from llm.antigravity_cli_client import AntigravityCLIClient
from llm.base_client import STREAM_ACTIVITY_KEEPALIVE
from llm.client_factory import create_llm_client



@pytest.mark.asyncio
async def test_openclaw_client_success(mocker):
    client = OpenClawClient(api_url="http://test", agent_id="123")
    mock_event_source = AsyncMock()
    async def mock_events():
        yield ServerSentEvent(event="response.output_text.delta", data='{"delta": "你好"}')
        yield ServerSentEvent(event="response.completed", data='{}')
    mock_event_source.aiter_sse = mock_events
    mock_aconnect_sse = mocker.patch("llm.openclaw_client.aconnect_sse", autospec=True)
    mock_aconnect_sse.return_value.__aenter__.return_value = mock_event_source

    results = [chunk async for chunk in client.send_message("測試")]
    assert results == ["你好"]
    kwargs = mock_aconnect_sse.call_args.kwargs
    assert kwargs["headers"]["x-openclaw-agent-id"] == "123"
    assert kwargs["json"]["model"] == "openclaw"
    assert kwargs["json"]["input"][0]["type"] == "message"

@pytest.mark.asyncio
async def test_openclaw_client_cancel(mocker):
    client = OpenClawClient(api_url="http://test")
    mock_event_source = AsyncMock()
    async def mock_events():
        yield ServerSentEvent(event="response.output_text.delta", data='{"delta": "你"}')
        await client.cancel()
        yield ServerSentEvent(event="response.output_text.delta", data='{"delta": "好"}')
    mock_event_source.aiter_sse = mock_events
    mock_aconnect_sse = mocker.patch("llm.openclaw_client.aconnect_sse")
    mock_aconnect_sse.return_value.__aenter__.return_value = mock_event_source

    results = [chunk async for chunk in client.send_message("測試")]
    assert results == ["你"]

@pytest.mark.asyncio
async def test_openclaw_client_error(mocker):
    client = OpenClawClient(api_url="http://test")
    mock_event_source = AsyncMock()
    async def mock_events():
        yield ServerSentEvent(event="response.failed", data='{"error": "bad"}')
    mock_event_source.aiter_sse = mock_events
    mock_aconnect_sse = mocker.patch("llm.openclaw_client.aconnect_sse")
    mock_aconnect_sse.return_value.__aenter__.return_value = mock_event_source

    with pytest.raises(RuntimeError, match="OpenClaw 錯誤"):
        async for _ in client.send_message("測試"): pass

@pytest.mark.asyncio
async def test_openclaw_client_progress_emits_keepalive(mocker):
    client = OpenClawClient(api_url="http://test")
    mock_event_source = AsyncMock()

    async def mock_events():
        yield ServerSentEvent(event="response.in_progress", data='{"id": "resp_1"}')
        yield ServerSentEvent(event="response.output_text.delta", data='{"delta": "你好"}')
        yield ServerSentEvent(event="response.completed", data='{"id": "resp_1"}')

    mock_event_source.aiter_sse = mock_events
    mock_aconnect_sse = mocker.patch("llm.openclaw_client.aconnect_sse")
    mock_aconnect_sse.return_value.__aenter__.return_value = mock_event_source

    results = [chunk async for chunk in client.send_message("測試")]

    assert results == [STREAM_ACTIVITY_KEEPALIVE, "你好"]
    assert client.previous_response_id == "resp_1"

@pytest.mark.asyncio
async def test_openclaw_refresh_session_resets_session_state():
    client = OpenClawClient(api_url="http://test", user="voice-assistant-old")
    client.previous_response_id = "resp_old"

    refreshed = await client.refresh_session()

    assert refreshed is True
    assert client.previous_response_id is None
    assert client.user.startswith("voice-assistant-")

@pytest.mark.asyncio
async def test_openclaw_request_error(mocker):
    client = OpenClawClient(api_url="http://test")
    mocker.patch("llm.openclaw_client.aconnect_sse",
                 side_effect=httpx.RequestError("Network Error", request=MagicMock()))
    with pytest.raises(RuntimeError, match="OpenClaw 連線錯誤"):
        async for _ in client.send_message("測試"): pass



@pytest.mark.asyncio
async def test_openclaw_reuses_async_client_until_close(mocker):
    created_clients = []

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout
            self.is_closed = False
            created_clients.append(self)

        async def aclose(self):
            self.is_closed = True

    mocker.patch("llm.openclaw_client.httpx.AsyncClient", side_effect=FakeAsyncClient)
    client = OpenClawClient(api_url="http://test", request_timeout_seconds=12.0)

    first = client._get_client()
    second = client._get_client()
    await client.aclose()
    third = client._get_client()
    await client.aclose()

    assert first is second
    assert first.is_closed is True
    assert third is not first
    assert third.timeout == 12.0
    assert len(created_clients) == 2


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



@pytest.mark.asyncio
async def test_gemini_client_success(mocker):
    mocker.patch("llm.gemini_cli_client.shutil.which", return_value="gemini")
    client = GeminiCLIClient()

    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.stdin = MagicMock()
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stderr = AsyncMock()

    stdout_queue = asyncio.Queue()
    for item in [
        b'{"jsonrpc":"2.0","id":1,"result":{}}\n',
        b'{"jsonrpc":"2.0","id":2,"result":{"sessionId":"123"}}\n',
        b'{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"123","update":{"sessionUpdate":"agent_message_chunk","content":{"text":"\\u4f60\\u597d"}}}}\n',
        b'{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"123","update":{"sessionUpdate":"agent_message_chunk","content":{"text":"\\u55ce"}}}}\n',
        b'{"jsonrpc":"2.0","id":3,"result":{"stopReason":"end_turn"}}\n',
        b''
    ]:
        stdout_queue.put_nowait(item)

    async def mock_readline():
        await asyncio.sleep(0.01)
        if stdout_queue.empty():
            return b''
        return await stdout_queue.get()

    mock_process.stdout.readline.side_effect = mock_readline
    mocker.patch("llm.gemini_cli_client.asyncio.create_subprocess_exec", return_value=mock_process)

    results = [chunk async for chunk in client.send_message("測試")]
    assert results == ["你好", "嗎"]
    assert client.session_id == "123"

@pytest.mark.asyncio
async def test_gemini_client_no_session(mocker):
    """If ACP fails to create session, yield error message."""
    client = GeminiCLIClient()
    mocker.patch("llm.gemini_cli_client.asyncio.create_subprocess_exec",
                 side_effect=Exception("Spawn Error"))
    results = [chunk async for chunk in client.send_message("測試")]
    assert results == ["無法連線至本地 AI 助理。"]

@pytest.mark.asyncio
async def test_gemini_client_cancel_precise_id(mocker):
    """cancel() should use ACP session/cancel and the correct request id fallback."""
    client = GeminiCLIClient()
    client.process = MagicMock()
    client.process.returncode = None
    client.session_id = "123"
    client._ready_event.set()
    client._active_prompt_req_id = 42

    mock_send = mocker.patch.object(client, "_send_notification", new_callable=AsyncMock)
    await client.cancel()

    assert client._cancel_flag is True
    mock_send.assert_has_awaits(
        [
            call("session/cancel", {"sessionId": "123"}),
            call("$/cancelRequest", {"requestId": 42}),
        ]
    )

@pytest.mark.asyncio
async def test_gemini_permission_request_returns_nested_outcome():
    client = GeminiCLIClient()
    client.process = MagicMock()
    client.process.stdin = MagicMock()
    client.process.stdin.write = MagicMock()
    client.process.stdin.drain = AsyncMock()

    await client._handle_server_request(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "session/request_permission",
            "params": {"toolName": "run_shell_command"},
        }
    )

    payload = client.process.stdin.write.call_args.args[0].decode("utf-8")
    response = json.loads(payload)

    assert response == {
        "jsonrpc": "2.0",
        "id": 99,
        "result": {
            "outcome": {
                "outcome": "selected",
                "optionId": "proceed_always",
            }
        },
    }

@pytest.mark.asyncio
async def test_gemini_stderr_suppresses_attach_console_trace(mocker):
    client = GeminiCLIClient()
    client.process = MagicMock()
    client.process.returncode = None

    stderr_lines = asyncio.Queue()
    for line in [
        b"C:\\Users\\testuser\\AppData\\Roaming\\npm\\node_modules\\@google\\gemini-cli\\node_modules\\@lydell\\node-pty\\conpty_console_list_agent.js:11\n",
        b"var consoleProcessList = getConsoleProcessList(shellPid);\n",
        b"^\n",
        b"Error: AttachConsole failed\n",
        b"at Object.<anonymous> (C:\\path\\conpty_console_list_agent.js:11:26)\n",
        b"Node.js v24.14.0\n",
        b"normal warning\n",
        b"",
    ]:
        stderr_lines.put_nowait(line)

    async def readline():
        return await stderr_lines.get()

    client.process.stderr = MagicMock()
    client.process.stderr.readline = AsyncMock(side_effect=readline)
    log_event_mock = mocker.patch("llm.gemini_cli_client.log_event")

    await client._stderr_loop()

    events = [call.args[2] for call in log_event_mock.call_args_list]
    assert events.count("acp.stderr_suppressed") == 1
    stderr_details = [
        call.kwargs.get("detail")
        for call in log_event_mock.call_args_list
        if call.args[2] == "acp.stderr"
    ]
    assert stderr_details == ["normal warning"]

@pytest.mark.asyncio
async def test_gemini_client_prompt_error_raises_runtime_error(mocker):
    mocker.patch("llm.gemini_cli_client.shutil.which", return_value="gemini")
    client = GeminiCLIClient()

    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.stdin = MagicMock()
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stderr = AsyncMock()

    stdout_queue = asyncio.Queue()
    for item in [
        b'{"jsonrpc":"2.0","id":1,"result":{}}\n',
        b'{"jsonrpc":"2.0","id":2,"result":{"sessionId":"123"}}\n',
        b'{"jsonrpc":"2.0","id":3,"error":{"code":500,"message":"boom"}}\n',
        b"",
    ]:
        stdout_queue.put_nowait(item)

    async def mock_readline():
        await asyncio.sleep(0.01)
        if stdout_queue.empty():
            return b""
        return await stdout_queue.get()

    mock_process.stdout.readline.side_effect = mock_readline
    mocker.patch("llm.gemini_cli_client.asyncio.create_subprocess_exec", return_value=mock_process)

    with pytest.raises(RuntimeError, match="Gemini CLI prompt failed: boom"):
        async for _ in client.send_message("hello"):
            pass

@pytest.mark.asyncio
async def test_gemini_client_thought_chunk_emits_keepalive(mocker):
    mocker.patch("llm.gemini_cli_client.shutil.which", return_value="gemini")
    client = GeminiCLIClient()

    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.stdin = MagicMock()
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stderr = AsyncMock()

    stdout_queue = asyncio.Queue()
    for item in [
        b'{"jsonrpc":"2.0","id":1,"result":{}}\n',
        b'{"jsonrpc":"2.0","id":2,"result":{"sessionId":"123"}}\n',
        b'{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"123","update":{"sessionUpdate":"agent_thought_chunk","content":{"text":"thinking"}}}}\n',
        b'{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"123","update":{"sessionUpdate":"agent_message_chunk","content":{"text":"\\u4f60\\u597d"}}}}\n',
        b'{"jsonrpc":"2.0","id":3,"result":{"stopReason":"end_turn"}}\n',
        b"",
    ]:
        stdout_queue.put_nowait(item)

    async def mock_readline():
        await asyncio.sleep(0.01)
        if stdout_queue.empty():
            return b""
        return await stdout_queue.get()

    mock_process.stdout.readline.side_effect = mock_readline
    mocker.patch("llm.gemini_cli_client.asyncio.create_subprocess_exec", return_value=mock_process)

    results = [chunk async for chunk in client.send_message("hello")]

    assert results == [STREAM_ACTIVITY_KEEPALIVE, "你好"]

@pytest.mark.asyncio
async def test_gemini_client_skips_replayed_message_after_tool_activity(mocker):
    mocker.patch("llm.gemini_cli_client.shutil.which", return_value="gemini")
    client = GeminiCLIClient()

    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.stdin = MagicMock()
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stderr = AsyncMock()

    stdout_queue = asyncio.Queue()
    for item in [
        b'{"jsonrpc":"2.0","id":1,"result":{}}\n',
        b'{"jsonrpc":"2.0","id":2,"result":{"sessionId":"123"}}\n',
        b'{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"123","update":{"sessionUpdate":"agent_message_chunk","content":{"text":"Hello "}}}}\n',
        b'{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"123","update":{"sessionUpdate":"agent_message_chunk","content":{"text":"world"}}}}\n',
        b'{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"123","update":{"sessionUpdate":"tool_call","toolCallId":"1","status":"in_progress","title":"memory update","content":[],"locations":[],"kind":"execute"}}}\n',
        b'{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"123","update":{"sessionUpdate":"tool_call_update","toolCallId":"1","status":"completed","title":"memory update","content":[],"locations":[],"kind":"execute"}}}\n',
        b'{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"123","update":{"sessionUpdate":"agent_message_chunk","content":{"text":"Hello wo"}}}}\n',
        b'{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"123","update":{"sessionUpdate":"agent_message_chunk","content":{"text":"rld"}}}}\n',
        b'{"jsonrpc":"2.0","id":3,"result":{"stopReason":"end_turn"}}\n',
        b"",
    ]:
        stdout_queue.put_nowait(item)

    async def mock_readline():
        await asyncio.sleep(0.01)
        if stdout_queue.empty():
            return b""
        return await stdout_queue.get()

    mock_process.stdout.readline.side_effect = mock_readline
    mocker.patch("llm.gemini_cli_client.asyncio.create_subprocess_exec", return_value=mock_process)

    results = [chunk async for chunk in client.send_message("hello")]

    assert results == [
        "Hello ",
        "world",
        STREAM_ACTIVITY_KEEPALIVE,
        STREAM_ACTIVITY_KEEPALIVE,
    ]

@pytest.mark.asyncio
async def test_gemini_client_waiting_for_ready_session_message():
    client = GeminiCLIClient()
    client.process = MagicMock(returncode=None)

    results = [chunk async for chunk in client.send_message("test")]

    assert len(results) == 1

@pytest.mark.asyncio
async def test_gemini_client_stale_session_start_failure_returns_error_immediately(mocker):
    client = GeminiCLIClient(session_id="stale-session")
    mocker.patch.object(client, "_start_acp", new_callable=AsyncMock)

    results = [chunk async for chunk in client.send_message("test")]

    assert results == ["無法連線至本地 AI 助理。"]

@pytest.mark.asyncio
async def test_gemini_start_acp_falls_back_to_new_session_when_load_fails(mocker):
    client = GeminiCLIClient(session_id="stale-session")
    mocker.patch("llm.gemini_cli_client.shutil.which", return_value="gemini")

    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.stdin = MagicMock()
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stderr = AsyncMock()

    stdout_queue = asyncio.Queue()
    for item in [
        b'{"jsonrpc":"2.0","id":1,"result":{}}\n',
        b'{"jsonrpc":"2.0","id":2,"error":{"message":"stale"}}\n',
        b'{"jsonrpc":"2.0","id":3,"result":{"sessionId":"fresh-session"}}\n',
        b'',
    ]:
        stdout_queue.put_nowait(item)

    async def mock_readline():
        if stdout_queue.empty():
            return b""
        return await stdout_queue.get()

    mock_process.stdout.readline.side_effect = mock_readline
    mocker.patch("llm.gemini_cli_client.asyncio.create_subprocess_exec", return_value=mock_process)

    await client._start_acp()

    assert client.session_id == "fresh-session"
    assert client._ready_event.is_set()

@pytest.mark.asyncio
async def test_gemini_client_cancel_no_active_request(mocker):
    """cancel() should still issue session/cancel even when request id fallback is unavailable."""
    client = GeminiCLIClient()
    client.process = MagicMock()
    client.process.returncode = None
    client.session_id = "123"
    client._ready_event.set()
    client._active_prompt_req_id = None

    mock_send = mocker.patch.object(client, "_send_notification", new_callable=AsyncMock)
    await client.cancel()

    assert client._cancel_flag is True
    mock_send.assert_awaited_once_with("session/cancel", {"sessionId": "123"})

@pytest.mark.asyncio
async def test_gemini_client_cancel_swallows_send_errors(mocker):
    client = GeminiCLIClient()
    client.process = MagicMock()
    client.process.returncode = None
    client.session_id = "123"
    client._ready_event.set()
    client._active_prompt_req_id = 42

    mocker.patch.object(client, "_send_notification", side_effect=RuntimeError("boom"))

    await client.cancel()

    assert client._cancel_flag is True

@pytest.mark.asyncio
async def test_gemini_aclose_logs_background_task_failures_without_raising(mocker):
    client = GeminiCLIClient()
    client.process = MagicMock()
    client.process.returncode = None
    client.process.kill = MagicMock()
    client.process.wait = AsyncMock(return_value=0)
    log_event = mocker.patch("llm.gemini_cli_client.log_event")

    async def failing_task():
        raise RuntimeError("boom")

    client._receive_task = asyncio.create_task(failing_task())
    client._stderr_task = asyncio.create_task(asyncio.sleep(0))
    await asyncio.sleep(0)

    await client.aclose()

    events = [call.args[2] for call in log_event.call_args_list]
    assert "acp.shutdown_task_failed" in events
    assert client.process is None

@pytest.mark.asyncio
async def test_gemini_client_task_leak_cleanup(mocker):
    """BUG-8 fix: queue_task must be cancelled in finally block."""
    client = GeminiCLIClient()

    client.session_id = "abc"
    client._ready_event.set()
    client.process = MagicMock()
    client.process.returncode = None


    async def immediate_response(method, params):
        return {"id": 1, "result": {"stopReason": "end_turn"}, "jsonrpc": "2.0"}

    mocker.patch.object(client, "_send_request", side_effect=immediate_response)

    results = [chunk async for chunk in client.send_message("test")]

    assert isinstance(results, list)
    assert client._active_prompt_req_id is None

@pytest.mark.asyncio
async def test_gemini_refresh_session(mocker):
    """refresh_session creates a new session without killing the process."""
    client = GeminiCLIClient()
    client.process = MagicMock()
    client.process.returncode = None
    client._ready_event.set()

    async def mock_send(method, params):
        return {"result": {"sessionId": "new_session"}, "jsonrpc": "2.0"}

    mocker.patch.object(client, "_send_request", side_effect=mock_send)
    refreshed = await client.refresh_session()
    assert refreshed is True
    assert client.session_id == "new_session"
    assert client._ready_event.is_set()

@pytest.mark.asyncio
async def test_gemini_refresh_session_starts_acp_when_process_missing(mocker):
    client = GeminiCLIClient(session_id="stale-session")

    async def fake_start():
        assert client.session_id is None
        client.process = MagicMock()
        client.process.returncode = None
        client.session_id = "fresh-session"

    mock_start = mocker.patch.object(client, "_start_acp", side_effect=fake_start)

    refreshed = await client.refresh_session()

    mock_start.assert_awaited_once()
    assert refreshed is True
    assert client.session_id == "fresh-session"


def test_gemini_stream_context_skips_duplicate_chunks():
    stream_context = _GeminiStreamContext()

    GeminiCLIClient._enqueue_stream_chunk(stream_context, "hello")
    GeminiCLIClient._enqueue_stream_chunk(stream_context, "hello")

    assert stream_context.queue.get_nowait() == "hello"
    assert stream_context.queue.empty()
    assert stream_context.emitted_text == "hello"


def test_gemini_stream_context_replay_boundary_emits_only_suffix():
    stream_context = _GeminiStreamContext()

    GeminiCLIClient._enqueue_stream_chunk(stream_context, "hello")
    GeminiCLIClient._mark_stream_replay_boundary(stream_context)
    GeminiCLIClient._enqueue_stream_chunk(stream_context, "hello world")

    assert stream_context.queue.get_nowait() == "hello"
    assert stream_context.queue.get_nowait() == " world"
    assert stream_context.queue.empty()
    assert stream_context.emitted_text == "hello world"


@pytest.mark.asyncio
async def test_gemini_ensure_ready_starts_acp(mocker):
    client = GeminiCLIClient()

    async def fake_start():
        client.process = MagicMock()
        client.process.returncode = None
        client.session_id = "fresh-session"
        client._ready_event.set()

    mock_start = mocker.patch.object(client, "_start_acp", side_effect=fake_start)

    assert await client.ensure_ready() is True
    mock_start.assert_awaited_once()
    assert client.session_id == "fresh-session"

@pytest.mark.asyncio
async def test_gemini_start_acp_rechecks_process_inside_spawn_lock(mocker):
    """Fix #4: do not spawn again when an existing process is alive."""
    client = GeminiCLIClient()

    client.process = MagicMock()
    client.process.returncode = None

    mock_spawn = mocker.patch(
        "llm.gemini_cli_client.asyncio.create_subprocess_exec",
        new_callable=AsyncMock
    )

    await client._start_acp()

    mock_spawn.assert_not_called()


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


def test_opencode_context_preload_missing_files_warns(mocker, tmp_path):
    log_event_mock = mocker.patch("llm.opencode_cli_client.log_event")
    client = OpenCodeCLIClient(
        project_dir=str(tmp_path),
        required_context_files=["MISSING_AGENTS.md"],
        instruction_files=["MISSING_MEMORY.md"],
    )

    client._before_start()

    events = [call.args[2] for call in log_event_mock.call_args_list]
    assert "opencode.required_context_file" in events
    assert "opencode.instruction_file" in events


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
async def test_codex_client_requires_login_returns_friendly_message(mocker):
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
        if stdout_queue.empty():
            return b""
        return await stdout_queue.get()

    mock_process.stdout.readline.side_effect = mock_stdout_readline
    mock_process.stderr.readline = AsyncMock(return_value=b"")
    mocker.patch("llm.codex_cli_client.asyncio.create_subprocess_exec", return_value=mock_process)

    results = [chunk async for chunk in client.send_message("測試")]

    assert results == ["Codex CLI 尚未登入，請先在終端執行 codex login，再重新啟動。"]

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

    with pytest.raises(RuntimeError, match="login required"):
        await client.ensure_ready()



def test_client_factory():
    client1 = create_llm_client("openclaw", token="123")
    assert isinstance(client1, OpenClawClient)
    assert client1.headers["Authorization"] == "Bearer 123"

    client2 = create_llm_client("claude_code", model="opus")
    assert isinstance(client2, ClaudeCodeClient)
    assert client2.model == "opus"
    assert client2.project_dir.endswith("agent_workspace")

    client3 = create_llm_client("gemini_cli", project_dir="/tmp")
    assert isinstance(client3, GeminiCLIClient)

    client4 = create_llm_client("codex_cli", project_dir="/tmp")
    assert isinstance(client4, CodexCLIClient)

    client5 = create_llm_client(
        "opencode_cli",
        project_dir="/tmp",
        model="",
        mode="",
        enable_web_search=True,
    )
    assert isinstance(client5, OpenCodeCLIClient)
    assert client5.model is None
    assert client5.mode is None
    assert client5.enable_web_search is True

    client6 = create_llm_client("antigravity_cli", project_dir="/tmp")
    assert isinstance(client6, AntigravityCLIClient)
    assert client6.session_id is None

    with pytest.raises(ValueError, match="未知"):
        create_llm_client("unknown")


def test_client_factory_ignores_runtime_session_state():
    gemini = create_llm_client("gemini_cli", project_dir="/tmp", session_id="stale-session")
    codex = create_llm_client("codex_cli", project_dir="/tmp", thread_id="stale-thread")
    opencode = create_llm_client("opencode_cli", project_dir="/tmp", session_id="stale-session")
    antigravity = create_llm_client("antigravity_cli", project_dir="/tmp", session_id="stale-session")

    assert gemini.session_id is None
    assert codex.thread_id is None
    assert opencode.session_id is None
    assert antigravity.session_id is None

