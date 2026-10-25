"""Shared ACP lifecycle regressions using only synthetic in-memory events."""

import asyncio
import gc
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import weakref

import pytest

from llm import acp_stdio_client as transport
from llm.acp_stdio_client import ACPStdioClient, _ACPStreamContext
from llm.base_client import LLMBackendUnavailableError, STREAM_ACTIVITY_KEEPALIVE


def make_client(tmp_path, **kwargs):
    return ACPStdioClient(
        backend_name="synthetic", project_dir=str(tmp_path),
        executable_names=[], command_args=[], initialize_params={"protocolVersion": 1},
        **kwargs,
    )


def make_ready(client):
    client.process = SimpleNamespace(returncode=None)
    client.session_id = "synthetic-session"
    client._ready_event.set()
    client.ensure_ready = AsyncMock(return_value=True)


def update(client, text, session_id=None):
    client._handle_session_update({
        "sessionId": session_id or client.session_id,
        "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}},
    })


async def collect(client, text="synthetic prompt"):
    return [chunk async for chunk in client.send_message(text) if chunk != STREAM_ACTIVITY_KEEPALIVE]


@pytest.mark.asyncio
@pytest.mark.parametrize("restore", [None, "resume", "load"])
async def test_shared_session_parameters_are_isolated_and_used_for_all_lifecycles(tmp_path, restore):
    servers = [{"name": "synthetic-mcp", "command": "synthetic-python", "args": ["-B", "server.py"], "env": []}]
    client = make_client(tmp_path, mcp_servers=servers)
    servers[0]["args"].append("caller mutation")
    params = client._session_parameters()
    params["mcpServers"][0]["args"].append("params mutation")
    assert client.mcp_servers[0]["args"] == ["-B", "server.py"]
    if restore:
        client.session_id = "existing-session"
        client._agent_capabilities = ({"sessionCapabilities": {"resume": {}}} if restore == "resume" else {"loadSession": True})
    client._send_request = AsyncMock(return_value={"result": {"sessionId": "ready-session"}})
    await client._setup_session()
    request = client._send_request.await_args
    assert request.args[0] == f"session/{restore or 'new'}"
    assert request.args[1]["mcpServers"] == client.mcp_servers
    assert request.args[1]["cwd"] == str(tmp_path.resolve())
    assert ("sessionId" in request.args[1]) == bool(restore)


@pytest.mark.asyncio
async def test_shared_session_validation_precedes_config_and_failures_never_prompt(tmp_path):
    client = make_client(tmp_path, model="synthetic-model")
    client._send_request = AsyncMock(return_value={"result": {"sessionId": "unverified"}})
    client._validate_session_result = Mock(side_effect=LLMBackendUnavailableError("synthetic entitlement denied"))
    client._apply_session_config_options = AsyncMock()
    with pytest.raises(LLMBackendUnavailableError):
        await client._setup_session()
    client._validate_session_result.assert_called_once()
    client._apply_session_config_options.assert_not_awaited()
    assert client.session_id is None
    assert [call.args[0] for call in client._send_request.await_args_list] == ["session/new"]


@pytest.mark.asyncio
async def test_shared_after_initialize_hook_runs_before_session_setup(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    events = []
    release = asyncio.Event()

    async def receive():
        await release.wait()

    async def after_initialize(result):
        events.append(("authenticated", result["protocolVersion"]))

    async def setup():
        assert events == [("authenticated", 1)]
        client.session_id = "session-after-auth"
        events.append(("session", client.session_id))

    client._build_command = Mock(return_value=["synthetic.exe"])
    client._receive_loop = receive
    client._stderr_loop = receive
    client._after_initialize = after_initialize
    client._setup_session = setup
    client._send_request = AsyncMock(return_value={"result": {"protocolVersion": 1, "agentCapabilities": {}}})
    monkeypatch.setattr(transport, "create_owned_subprocess", AsyncMock(return_value=(SimpleNamespace(returncode=None), None)))
    try:
        await client._start_acp()
        assert events == [("authenticated", 1), ("session", "session-after-auth")]
        assert client._ready_event.is_set()
    finally:
        release.set()
        await asyncio.gather(client._receive_task, client._stderr_task)


@pytest.mark.asyncio
async def test_refresh_waits_until_active_turn_finishes_and_uses_mcp_parameters(tmp_path):
    client = make_client(tmp_path, mcp_servers=[{"name": "synthetic", "command": "python", "args": [], "env": []}])
    make_ready(client)
    prompt_started = asyncio.Event()
    finish_prompt = asyncio.Event()
    methods = []

    async def respond(method, params, **kwargs):
        methods.append(method)
        if method == "session/prompt":
            prompt_started.set()
            await finish_prompt.wait()
            update(client, "first complete")
            return {"result": {"stopReason": "end_turn"}}
        assert method == "session/new"
        assert params["mcpServers"] == client.mcp_servers
        return {"result": {"sessionId": "refreshed-session"}}

    client._send_request = AsyncMock(side_effect=respond)
    first = asyncio.create_task(collect(client))
    await asyncio.wait_for(prompt_started.wait(), 1)
    refresh = asyncio.create_task(client.refresh_session())
    await asyncio.sleep(0)
    assert methods == ["session/prompt"]
    assert not refresh.done()
    finish_prompt.set()
    assert await asyncio.wait_for(first, 1) == ["first complete"]
    assert await asyncio.wait_for(refresh, 1) is True
    assert client.session_id == "refreshed-session"


@pytest.mark.asyncio
async def test_two_prompts_never_overlap_on_the_same_session(tmp_path):
    client = make_client(tmp_path)
    make_ready(client)
    first_started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def respond(method, params, **kwargs):
        calls.append(params["prompt"][-1]["text"])
        if len(calls) == 1:
            first_started.set()
            await release.wait()
        update(client, calls[-1])
        return {"result": {"stopReason": "end_turn"}}

    client._send_request = AsyncMock(side_effect=respond)
    first = asyncio.create_task(collect(client, "first"))
    await asyncio.wait_for(first_started.wait(), 1)
    second = asyncio.create_task(collect(client, "second"))
    await asyncio.sleep(0)
    assert calls == ["first"]
    release.set()
    assert await asyncio.wait_for(first, 1) == ["first"]
    assert await asyncio.wait_for(second, 1) == ["second"]


@pytest.mark.asyncio
async def test_cancel_during_startup_never_sends_a_prompt(tmp_path):
    client = make_client(tmp_path)
    make_ready(client)
    startup_started, finish_startup = asyncio.Event(), asyncio.Event()

    async def ready():
        startup_started.set()
        await finish_startup.wait()
        return True

    client.ensure_ready = ready
    client._send_request = AsyncMock(return_value={"result": {"stopReason": "end_turn"}})
    client._send_notification = AsyncMock()
    pending = asyncio.create_task(collect(client))
    await asyncio.wait_for(startup_started.wait(), 1)
    client.request_cancel()
    finish_startup.set()
    assert await asyncio.wait_for(pending, 1) == []
    client._send_request.assert_not_awaited()
    assert client._streaming_queues == {}


@pytest.mark.asyncio
async def test_prompt_build_failure_leaves_no_stream_context_or_active_request(tmp_path):
    client = make_client(tmp_path)
    make_ready(client)
    client._build_prompt = Mock(side_effect=LLMBackendUnavailableError("synthetic context rejected"))
    client._send_request = AsyncMock()
    with pytest.raises(LLMBackendUnavailableError):
        await collect(client)
    assert client._streaming_queues == {}
    assert client._active_prompt_req_id is None
    client._send_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_ack_drains_old_turn_and_next_turn_is_clean(tmp_path):
    client = make_client(tmp_path, stream_mode="final_segment")
    make_ready(client)
    started = asyncio.Event()
    canceled_response = asyncio.get_running_loop().create_future()
    requests = 0

    async def respond(method, params, **kwargs):
        nonlocal requests
        requests += 1
        if requests == 1:
            update(client, "old pending text")
            started.set()
            return await canceled_response
        update(client, "fresh reply")
        return {"result": {"stopReason": "end_turn"}}

    async def notify(method, params):
        assert method in {"session/cancel", "$/cancelRequest"}
        if not canceled_response.done():
            canceled_response.set_result({"result": {"stopReason": "cancelled"}})

    client._send_request = AsyncMock(side_effect=respond)
    client._send_notification = AsyncMock(side_effect=notify)
    client._terminate_process = AsyncMock()
    pending = asyncio.create_task(collect(client))
    await asyncio.wait_for(started.wait(), 1)
    client.request_cancel()
    assert await asyncio.wait_for(pending, 1) == []
    assert client._streaming_queues == {}
    update(client, "late old update with no active turn")
    assert await collect(client, "next") == ["fresh reply"]
    client._terminate_process.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_and_prompt_response_in_same_loop_tick_cannot_emit_old_final(tmp_path):
    client = make_client(tmp_path, stream_mode="final_segment")
    make_ready(client)
    started = asyncio.Event()
    response = asyncio.get_running_loop().create_future()

    async def respond(*args, **kwargs):
        update(client, "canceled answer must not reach TTS")
        started.set()
        return await response

    client._send_request = AsyncMock(side_effect=respond)
    client._send_notification = AsyncMock()
    client._prompt_completed = Mock()
    pending = asyncio.create_task(collect(client))
    await asyncio.wait_for(started.wait(), 1)
    response.set_result({"result": {"stopReason": "cancelled"}})
    client.request_cancel()
    assert await asyncio.wait_for(pending, 1) == []
    client._prompt_completed.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("activity_type", ["agent_thought_chunk", "tool_call_update"])
async def test_cancel_after_consumer_receives_activity_does_not_emit_or_commit_ready_final(tmp_path, activity_type):
    client = make_client(tmp_path, stream_mode="final_segment")
    make_ready(client)

    async def respond(*args, **kwargs):
        client._handle_session_update({"sessionId": client.session_id, "update": {
            "sessionUpdate": activity_type, "toolCallId": "synthetic-tool", "status": "in_progress",
        }})
        update(client, "canceled final must not reach TTS")
        return {"result": {"stopReason": "end_turn"}}

    client._send_request = AsyncMock(side_effect=respond)
    client._send_notification = AsyncMock()
    client._prompt_completed = Mock()
    stream = client.send_message("synthetic prompt")
    assert await asyncio.wait_for(stream.__anext__(), 1) == STREAM_ACTIVITY_KEEPALIVE
    client.request_cancel()
    assert [chunk async for chunk in stream] == []
    client._prompt_completed.assert_not_called()
    assert client._streaming_queues == {}
    assert client._active_prompt_req_id is None
    assert not client._turn_lock.locked()


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer_action", ["cancel", "close"])
async def test_done_prompt_failure_is_retrieved_when_consumer_stops_after_keepalive(tmp_path, consumer_action):
    client = make_client(tmp_path, stream_mode="final_segment")
    make_ready(client)
    error = RuntimeError("synthetic prompt failure after activity")
    prompt_references = []
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    unhandled = []

    async def respond(*args, **kwargs):
        prompt_references.append(weakref.ref(asyncio.current_task()))
        client._handle_session_update({"sessionId": client.session_id, "update": {
            "sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "synthetic activity"},
        }})
        raise error

    client._send_request = AsyncMock(side_effect=respond)
    client._send_notification = AsyncMock()
    client._prompt_completed = Mock()
    stream = client.send_message("synthetic prompt")
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
    try:
        assert await asyncio.wait_for(stream.__anext__(), 1) == STREAM_ACTIVITY_KEEPALIVE
        if consumer_action == "cancel":
            client.request_cancel()
            assert [chunk async for chunk in stream] == []
        else:
            await stream.aclose()
        gc.collect()
        await asyncio.sleep(0)
        assert not [context for context in unhandled if context.get("exception") is error]
        assert prompt_references[0]() is None
        client._prompt_completed.assert_not_called()
        assert client._streaming_queues == {}
        assert client._active_prompt_req_id is None
        assert not client._turn_lock.locked()
    finally:
        await stream.aclose()
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
async def test_normal_prompt_failure_still_propagates_after_cleanup_gather(tmp_path):
    client = make_client(tmp_path)
    make_ready(client)
    client._send_request = AsyncMock(side_effect=RuntimeError("synthetic expected prompt failure"))
    client._prompt_completed = Mock()
    with pytest.raises(RuntimeError, match="synthetic expected prompt failure"):
        await collect(client)
    client._prompt_completed.assert_not_called()
    assert client._streaming_queues == {}
    assert client._active_prompt_req_id is None
    assert not client._turn_lock.locked()


@pytest.mark.asyncio
async def test_cancel_grace_timeout_terminates_only_the_owned_process(tmp_path):
    client = make_client(tmp_path)
    make_ready(client)
    owned_process = client.process
    started, never_finishes = asyncio.Event(), asyncio.Event()

    async def respond(*args, **kwargs):
        started.set()
        await never_finishes.wait()

    async def terminate(process):
        assert process is owned_process
        process.returncode = -1

    client._send_request = AsyncMock(side_effect=respond)
    client._send_notification = AsyncMock()
    client._terminate_process = AsyncMock(side_effect=terminate)
    pending = asyncio.create_task(collect(client))
    await asyncio.wait_for(started.wait(), 1)
    client.request_cancel()
    assert await asyncio.wait_for(pending, 4) == []
    client._terminate_process.assert_awaited_once_with(owned_process)
    assert client._streaming_queues == {}
    assert not client._ready_event.is_set()


@pytest.mark.asyncio
async def test_consumer_close_finishes_remote_cancel_before_next_turn_gets_lock(tmp_path):
    client = make_client(tmp_path)
    make_ready(client)
    canceled = asyncio.get_running_loop().create_future()
    cancel_sent = asyncio.Event()
    next_started = asyncio.Event()

    async def respond(method, params, **kwargs):
        if params["prompt"][-1]["text"] == "first":
            update(client, "first partial answer")
            return await canceled
        next_started.set()
        update(client, "next clean answer")
        return {"result": {"stopReason": "end_turn"}}

    async def notify(method, params):
        assert method == "session/cancel"
        cancel_sent.set()

    client._send_request = AsyncMock(side_effect=respond)
    client._send_notification = AsyncMock(side_effect=notify)
    stream = client.send_message("first")
    assert await asyncio.wait_for(stream.__anext__(), 1) == "first partial answer"
    closing = asyncio.create_task(stream.aclose())
    following = None
    try:
        await asyncio.wait_for(cancel_sent.wait(), 1)
        assert client._turn_lock.locked()
        assert not closing.done()
        following = asyncio.create_task(collect(client, "next"))
        await asyncio.sleep(0)
        assert not next_started.is_set()
        assert client._send_request.await_count == 1
        canceled.set_result({"result": {"stopReason": "cancelled"}})
        await asyncio.wait_for(closing, 1)
        assert await asyncio.wait_for(following, 1) == ["next clean answer"]
        assert client._streaming_queues == {}
        assert client._active_prompt_req_id is None
        assert not client._turn_lock.locked()
    finally:
        if not canceled.done():
            canceled.set_result({"result": {"stopReason": "cancelled"}})
        await asyncio.gather(closing, *([following] if following is not None else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_consumer_close_of_completed_final_cleans_up_without_cancel(tmp_path):
    client = make_client(tmp_path, stream_mode="final_segment")
    make_ready(client)

    async def respond(*args, **kwargs):
        update(client, "complete final answer")
        return {"result": {"stopReason": "end_turn"}}

    client._send_request = AsyncMock(side_effect=respond)
    client._send_notification = AsyncMock()
    stream = client.send_message("first")
    assert await asyncio.wait_for(stream.__anext__(), 1) == "complete final answer"
    await asyncio.wait_for(stream.aclose(), 1)
    assert client._streaming_queues == {}
    assert client._active_prompt_req_id is None
    assert not client._turn_lock.locked()
    client._send_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_consumer_close_before_iteration_never_starts_a_prompt(tmp_path):
    client = make_client(tmp_path)
    make_ready(client)
    client._send_request = AsyncMock()
    client._send_notification = AsyncMock()
    stream = client.send_message("never started")
    await stream.aclose()
    assert client._streaming_queues == {}
    assert client._active_prompt_req_id is None
    assert not client._turn_lock.locked()
    client.ensure_ready.assert_not_awaited()
    client._send_request.assert_not_awaited()
    client._send_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_consumer_task_cancel_during_startup_releases_lock_without_prompt(tmp_path):
    client = make_client(tmp_path)
    make_ready(client)
    started, never_ready = asyncio.Event(), asyncio.Event()

    async def ready():
        started.set()
        await never_ready.wait()

    client.ensure_ready = ready
    client._send_request = AsyncMock()
    client._send_notification = AsyncMock()
    pending = asyncio.create_task(collect(client, "not yet sent"))
    await asyncio.wait_for(started.wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert client._streaming_queues == {}
    assert client._active_prompt_req_id is None
    assert not client._turn_lock.locked()
    client._send_request.assert_not_awaited()
    client._send_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_segment_survives_a_trailing_completed_tool_update(tmp_path):
    client = make_client(tmp_path, stream_mode="final_segment")
    make_ready(client)

    async def respond(*args, **kwargs):
        update(client, "final spoken answer")
        client._handle_session_update({"sessionId": client.session_id, "update": {
            "sessionUpdate": "tool_call_update", "toolCallId": "old-tool", "status": "completed",
        }})
        return {"result": {"stopReason": "end_turn"}}

    client._send_request = AsyncMock(side_effect=respond)
    assert await collect(client) == ["final spoken answer"]


def test_private_error_messages_and_tool_titles_are_never_logged(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    private_marker = "SYNTHETIC_PRIVATE_TOOL_PAYLOAD"
    records = []
    monkeypatch.setattr(transport, "log_event", lambda logger, level, event, **fields: records.append((event, fields)))
    with pytest.raises(RuntimeError):
        client._handle_response_error({"error": {"code": -32603, "message": private_marker}}, "session/prompt")
    client.session_id = "synthetic-session"
    client._streaming_queues[client.session_id] = _ACPStreamContext()
    client._handle_session_update({"sessionId": client.session_id, "update": {
        "sessionUpdate": "tool_call_update", "toolCallId": "tool-1", "status": "failed", "title": private_marker,
    }})
    assert private_marker not in json.dumps(records)
