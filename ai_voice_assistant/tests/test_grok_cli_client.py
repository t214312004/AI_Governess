import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from llm.base_client import STREAM_ACTIVITY_KEEPALIVE
from llm.grok_cli_client import GrokCLIClient


def _make_mock_process(stdout_items):
    process = MagicMock()
    process.returncode = None
    process.stdin = MagicMock()
    process.stdin.drain = AsyncMock()
    process.stdout = AsyncMock()
    process.stderr = AsyncMock()
    process.stderr.readline = AsyncMock(return_value=b"")
    process.wait = AsyncMock(return_value=0)

    queue = asyncio.Queue()
    for item in stdout_items:
        queue.put_nowait(item.encode("utf-8") if isinstance(item, str) else item)

    async def readline():
        await asyncio.sleep(0.01)
        if queue.empty():
            return b""
        return await queue.get()

    process.stdout.readline.side_effect = readline
    return process


def _written_messages(process):
    messages = []
    for write_call in process.stdin.write.call_args_list:
        payload = write_call.args[0]
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        messages.append(json.loads(payload))
    return messages


def _make_workspace(tmp_path):
    (tmp_path / "AGENTS.md").write_text("private rules", encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text("private memory", encoding="utf-8")
    return tmp_path


def test_grok_runtime_profile_preloads_private_context_and_restricts_tools(tmp_path):
    client = GrokCLIClient(
        project_dir=str(_make_workspace(tmp_path)),
        enable_web_search=False,
        enable_subagents=False,
    )

    client._before_start()
    profile_path = client._agent_profile_path
    assert profile_path is not None
    profile = profile_path.read_text(encoding="utf-8")

    assert "agents_md: false" in profile
    assert "private rules" in profile
    assert "private memory" in profile
    assert "  - web_search" in profile
    assert client._build_subprocess_env()["GROK_SUBAGENTS"] == "0"
    assert client.command_args[:3] == ["--no-auto-update", "--no-memory", "agent"]
    assert client.command_args[-1] == "stdio"

    client._cleanup_agent_profile()
    assert not profile_path.exists()


def test_grok_command_uses_model_reasoning_and_profile(tmp_path):
    client = GrokCLIClient(
        project_dir=str(_make_workspace(tmp_path)),
        model="grok-4.5",
        reasoning_effort="high",
    )

    client._before_start()

    assert ["--model", "grok-4.5"] == client.command_args[3:5]
    assert ["--reasoning-effort", "high"] == client.command_args[5:7]
    assert "--agent-profile" in client.command_args
    client._cleanup_agent_profile()


@pytest.mark.asyncio
async def test_grok_authenticates_and_returns_only_final_post_tool_segment(mocker, tmp_path):
    client = GrokCLIClient(project_dir=str(_make_workspace(tmp_path)))
    process = _make_mock_process(
        [
            '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":1,"authMethods":[{"id":"cached_token"}],"agentCapabilities":{"loadSession":true}}}\n',
            '{"jsonrpc":"2.0","id":2,"result":{}}\n',
            '{"jsonrpc":"2.0","id":3,"result":{"sessionId":"grok-1"}}\n',
            '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"grok-1","update":{"sessionUpdate":"agent_message_chunk","content":{"text":"I will search."}}}}\n',
            '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"grok-1","update":{"sessionUpdate":"tool_call","toolCallId":"t1","title":"Web search:"}}}\n',
            '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"grok-1","update":{"sessionUpdate":"agent_message_chunk","content":{"text":"Still searching."}}}}\n',
            '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"grok-1","update":{"sessionUpdate":"tool_call_update","toolCallId":"t1","status":"completed"}}}\n',
            '{"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"grok-1","update":{"sessionUpdate":"agent_message_chunk","content":{"text":"Final answer."}}}}\n',
            '{"jsonrpc":"2.0","id":4,"result":{"stopReason":"end_turn"}}\n',
            b"",
        ]
    )
    mocker.patch.object(client, "_find_executable", return_value="grok.exe")
    spawn = mocker.patch(
        "llm.acp_stdio_client.asyncio.create_subprocess_exec",
        return_value=process,
    )

    results = [chunk async for chunk in client.send_message("search")]

    assert results == [
        STREAM_ACTIVITY_KEEPALIVE,
        STREAM_ACTIVITY_KEEPALIVE,
        "Final answer.",
    ]
    messages = _written_messages(process)
    assert [message["method"] for message in messages] == [
        "initialize",
        "authenticate",
        "session/new",
        "session/prompt",
    ]
    assert messages[1]["params"]["methodId"] == "cached_token"
    command = list(spawn.call_args.args)
    assert command[0] == "grok.exe"
    profile_index = command.index("--agent-profile") + 1
    assert not Path(command[profile_index]).exists()


@pytest.mark.asyncio
async def test_grok_permission_auto_approve_prefers_allow_once(tmp_path):
    client = GrokCLIClient(project_dir=str(_make_workspace(tmp_path)))
    client.process = MagicMock()
    client.process.stdin = MagicMock()
    client.process.stdin.drain = AsyncMock()

    await client._handle_server_request(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "session/request_permission",
            "params": {
                "options": [
                    {"optionId": "allow-session", "kind": "allow_always"},
                    {"optionId": "allow-once", "kind": "allow_once"},
                ]
            },
        }
    )

    response = json.loads(client.process.stdin.write.call_args.args[0].decode("utf-8"))
    assert response["result"]["outcome"]["optionId"] == "allow-once"


@pytest.mark.asyncio
async def test_grok_authentication_fails_without_noninteractive_method(tmp_path):
    client = GrokCLIClient(project_dir=str(_make_workspace(tmp_path)))

    with pytest.raises(RuntimeError, match="grok login"):
        await client._after_initialize(
            {"authMethods": [{"id": "grok.com", "name": "Grok"}]}
        )


def test_grok_auxiliary_title_errors_are_debug_only():
    title_error = "WARN session title generation failed for grok-build"
    real_error = "ERROR main response failed"

    assert GrokCLIClient._stderr_event_level(title_error) == logging.DEBUG
    assert GrokCLIClient._stderr_event_level(real_error) == logging.WARNING


def test_grok_serialized_false_flags_remain_disabled(tmp_path):
    client = GrokCLIClient(
        project_dir=str(_make_workspace(tmp_path)),
        auto_approve="false",
        enable_web_search="false",
        enable_subagents="false",
        load_private_context="false",
    )

    assert client.auto_approve is False
    assert client.enable_web_search is False
    assert client.enable_subagents is False
    assert client.load_private_context is False
