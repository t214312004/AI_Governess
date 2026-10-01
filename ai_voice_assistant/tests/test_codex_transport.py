import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from llm.codex_cli_client import CodexCLIClient
from llm.base_client import STREAM_ACTIVITY_KEEPALIVE


@pytest.mark.asyncio
async def test_codex_tracks_only_current_turn_progress(mocker, tmp_path):
    client = CodexCLIClient(project_dir=str(tmp_path), thread_id="thread-1")
    state = client._get_turn_state("turn-1")
    mocker.patch("llm.codex_cli_client.time.monotonic", return_value=123.0)
    await client._handle_notification("thread/tokenUsage/updated", {"threadId": "thread-1"})
    await client._handle_notification("item/commandExecution/outputDelta", {
        "threadId": "other-thread", "turnId": "turn-1", "delta": "output"
    })
    await client._handle_notification("item/commandExecution/outputDelta", {
        "threadId": "thread-1", "turnId": "other-turn", "delta": "output"
    })
    assert client.last_backend_progress_at is None
    assert not state.progress.is_set()
    await client._handle_notification("item/commandExecution/outputDelta", {
        "threadId": "thread-1", "turnId": "turn-1", "delta": "output"
    })
    assert client.last_backend_progress_at == 123.0
    assert state.progress.is_set()


@pytest.mark.asyncio
async def test_codex_progress_wakes_stream_before_periodic_keepalive(mocker, tmp_path):
    mocker.patch("llm.codex_cli_client._TURN_KEEPALIVE_INTERVAL_SECONDS", 60.0)
    client = CodexCLIClient(project_dir=str(tmp_path), thread_id="thread-1")
    client.process = MagicMock(returncode=None)
    client._ready_event.set()
    mocker.patch.object(client, "_send_request", new=AsyncMock(return_value={
        "result": {"turn": {"id": "turn-1"}}
    }))
    stream = client.send_message("work")
    next_chunk = asyncio.create_task(anext(stream))
    try:
        for _ in range(100):
            if "turn-1" in client._turn_states:
                break
            await asyncio.sleep(0.001)
        await client._handle_notification("item/reasoning/textDelta", {
            "threadId": "thread-1", "turnId": "turn-1", "delta": "thinking"
        })
        assert await asyncio.wait_for(next_chunk, timeout=1.0) == STREAM_ACTIVITY_KEEPALIVE
        assert client.last_backend_progress_at is not None
    finally:
        next_chunk.cancel()
        await asyncio.gather(next_chunk, return_exceptions=True)
        await stream.aclose()
        client.process = None


@pytest.mark.asyncio
async def test_codex_large_tool_event_preserves_connection(mocker, tmp_path):
    """Exercise real subprocess pipes, not mocked readline calls."""
    server = r'''
import json, sys
def emit(data):
    print(json.dumps(data), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if "id" not in request:
        continue
    result = {}
    if method == "account/read":
        result = {"account": {"type": "chatgpt"}, "requiresOpenaiAuth": True}
    elif method == "thread/start":
        result = {"thread": {"id": "thread-1"}}
    elif method == "turn/start":
        turn = "turn-" + str(request["id"])
        result = {"turn": {"id": turn, "status": "inProgress"}}
    emit({"id": request["id"], "result": result})
    if method == "turn/start":
        emit({"method": "turn/started", "params": {"turn": {"id": turn}}})
        emit({"method": "item/completed", "params": {
            "turnId": turn, "item": {"id": "tool", "type": "commandExecution",
            "aggregatedOutput": "x" * (256 * 1024)}}})
        # stderr uses the same subprocess stream limit.
        sys.stderr.write("x" * (128 * 1024) + "\n")
        sys.stderr.flush()
        emit({"method": "item/started", "params": {"turnId": turn,
            "item": {"id": "answer", "type": "agentMessage", "phase": "final_answer"}}})
        emit({"method": "item/agentMessage/delta", "params": {
            "turnId": turn, "itemId": "answer", "delta": "ok"}})
        emit({"method": "turn/completed", "params": {
            "turn": {"id": turn, "status": "completed"}}})
'''
    spawn = asyncio.create_subprocess_exec

    async def start_fake_server(*args, **kwargs):
        return await spawn(sys.executable, "-u", "-c", server, **kwargs)

    mocker.patch(
        "llm.codex_cli_client.asyncio.create_subprocess_exec",
        side_effect=start_fake_server,
    )
    client = CodexCLIClient(project_dir=str(tmp_path), model="test-model")
    try:
        assert [chunk async for chunk in client.send_message("first")
                if chunk != STREAM_ACTIVITY_KEEPALIVE] == ["ok"]
        process = client.process
        assert [chunk async for chunk in client.send_message("second")
                if chunk != STREAM_ACTIVITY_KEEPALIVE] == ["ok"]
        assert client.process is process
        assert not client._receive_task.done()
        assert not client._stderr_task.done()
    finally:
        # Close stdin so the fake server exits without platform taskkill.
        if client.process:
            client.process.stdin.close()
            await asyncio.wait_for(client.process.wait(), timeout=5)
        await client.aclose()


@pytest.mark.asyncio
async def test_codex_reader_failure_reports_category_without_private_data(mocker, tmp_path):
    client = CodexCLIClient(project_dir=str(tmp_path))
    client.process = MagicMock(returncode=None)
    client.process.stdout.readline = AsyncMock(side_effect=ValueError("private output"))
    client._ready_event.set()
    state = client._get_turn_state("turn-1")
    future = asyncio.get_running_loop().create_future()
    client._response_futures[1] = future
    log_event = mocker.patch("llm.codex_cli_client.log_event")

    await client._receive_loop()

    assert state.done.is_set()
    assert str(state.error) == "Codex CLI stdout reader failed (ValueError)"
    with pytest.raises(RuntimeError, match="stdout reader failed"):
        await future
    assert not client._ready_event.is_set()
    failure = next(c for c in log_event.call_args_list if c.args[2] == "codex.receive_failed")
    assert failure.kwargs["error_type"] == "ValueError"
    assert "private output" not in str(log_event.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["ensure_ready", "refresh_session", "send_message"])
async def test_codex_dead_reader_restarts_server(mocker, tmp_path, operation):
    client = CodexCLIClient(project_dir=str(tmp_path), model="test-model")
    old_process = MagicMock(returncode=None)
    client.process = old_process
    client.thread_id = "old-thread"
    client._receive_task = asyncio.create_task(asyncio.sleep(0))
    await client._receive_task
    cleanup = mocker.patch.object(client, "_cleanup_failed_start", new=AsyncMock())
    new_process = MagicMock(returncode=None)
    spawn = mocker.patch(
        "llm.codex_cli_client.asyncio.create_subprocess_exec", return_value=new_process
    )

    async def respond(method, params):
        if method == "account/read":
            return {"result": {"account": {"type": "chatgpt"}}}
        if method in ("thread/start", "thread/resume"):
            return {"result": {"thread": {"id": "new-thread"}}}
        if method == "turn/start":
            await client._handle_notification("turn/started", {"turn": {"id": "turn-1"}})
            await client._handle_notification(
                "turn/completed", {"turn": {"id": "turn-1", "status": "completed"}}
            )
            return {"result": {"turn": {"id": "turn-1"}}}
        return {"result": {}}

    mocker.patch.object(client, "_send_request", side_effect=respond)
    mocker.patch.object(client, "_send_notification", new=AsyncMock())
    mocker.patch.object(client, "_receive_loop", new=AsyncMock())
    mocker.patch.object(client, "_stderr_loop", new=AsyncMock())
    try:
        if operation == "send_message":
            assert [chunk async for chunk in client.send_message("retry")] == []
        else:
            assert await getattr(client, operation)()
        cleanup.assert_awaited_once()
        spawn.assert_awaited_once()
        assert client.process is new_process
        assert client.thread_id == "new-thread"
    finally:
        await client._receive_task
        await client._stderr_task
        client.process = None
