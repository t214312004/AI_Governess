"""Provider-specific subscription and session contracts for official ACP.

Transport behavior is covered by the shared ACP suite. These tests use only
synthetic profiles/workspaces and never contact Google or read real credentials.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from llm.acp_stdio_client import ACPStdioClient
from llm.antigravity_acp_client import AntigravityACPClient
from llm.base_client import LLMBackendUnavailableError


@pytest.fixture
def personal_profile(monkeypatch, tmp_path):
    home = tmp_path / "synthetic-gemini-home"
    profile = home / "antigravity-acp" / "settings.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(json.dumps({"auth": {"type": "oauth-personal"}}), encoding="utf-8")
    monkeypatch.setenv("GEMINI_HOME", str(home))
    return profile


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace 中文 with spaces"
    root.mkdir()
    (root / "AGENTS.md").write_text("# 私人規則\nSYNTHETIC_RULES_KEEP\n", encoding="utf-8")
    (root / "MEMORY.md").write_text("# 私人記憶\nSYNTHETIC_MEMORY_COBALT\n", encoding="utf-8")
    return root


def session_result(*, session_id="synthetic-session", tier="g1-pro-tier"):
    return {
        "sessionId": session_id,
        "_meta": {"antigravity": {"tier": {"id": tier, "name": "Google AI Pro"}}},
        "configOptions": [
            {"id": "model", "category": "model", "currentValue": "gemini-4-argon", "options": [
                {"value": "gemini-4-argon"}, {"value": "gemini-3.8-flash"},
            ]},
            {"id": "mode", "category": "mode", "currentValue": "default", "options": [
                {"value": "default"}, {"value": "yolo"},
            ]},
            {"id": "thinking_level", "category": "thought_level", "currentValue": "high", "options": [
                {"value": "low"}, {"value": "medium"}, {"value": "high"},
            ]},
        ],
    }


def test_provider_uses_shared_transport_and_yolo_defaults(workspace):
    client = AntigravityACPClient(project_dir=str(workspace))

    assert isinstance(client, ACPStdioClient)
    assert client.command_args == []
    assert client.session_id is None
    assert client.mode == "yolo"
    assert client.auto_approve is True
    assert client.auto_approve_scope == "once"
    assert client.stream_mode == "final_segment"
    assert client.auth_method == "oauth-personal"
    assert client.request_timeout_seconds == 120
    assert client.startup_timeout_seconds == 90


def test_catalog_session_has_no_filesystem_mcp_and_cannot_send_prompt(workspace):
    client = AntigravityACPClient(project_dir=str(workspace), mcp_servers=[])
    client._catalog_only = True
    assert client._session_parameters()["mcpServers"] == []
    with pytest.raises(LLMBackendUnavailableError, match="查詢 session"):
        client._build_prompt("must never be sent")


def test_factory_preserves_provider_settings_and_drops_runtime_session_id(workspace, tmp_path):
    from llm.client_factory import create_llm_client
    extra_root = tmp_path / "authorized extra root"
    extra_root.mkdir()
    client = create_llm_client(
        "antigravity_cli", project_dir=str(workspace), executable="synthetic-server.exe",
        model="gemini-4-argon-medium", effort="medium", mode="default",
        auto_approve=False, startup_timeout_seconds=91, request_timeout_seconds=121,
        filesystem_roots=[str(extra_root)], session_id="must-not-resume-from-public-config",
        mcp_servers=[{"name": "synthetic", "command": "synthetic.exe", "args": [], "env": []}],
    )

    assert isinstance(client, AntigravityACPClient)
    assert client.session_id is None
    assert client.executable == "synthetic-server.exe"
    assert (client.model, client.config_reasoning_effort, client.mode) == ("gemini-4-argon", "medium", "default")
    assert client.auto_approve is False
    assert (client.startup_timeout_seconds, client.request_timeout_seconds) == (91, 121)
    servers = client._session_parameters()["mcpServers"]
    assert any(item["name"] == "synthetic" for item in servers)
    filesystem = next(item for item in servers if item["name"] == "governess_filesystem")
    env = {item["name"]: item["value"] for item in filesystem["env"]}
    assert str(extra_root.resolve()) in json.loads(env["AI_GOVERNESS_FILESYSTEM_ROOTS"])


def test_relative_profile_home_is_identical_in_parent_and_server(workspace, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    client = AntigravityACPClient(project_dir=str(workspace), env_overrides={"GEMINI_HOME": "relative-home"})
    profile = client.profile_path
    profile.parent.mkdir(parents=True)
    profile.write_text('{"auth":{"type":"oauth-personal"}}', encoding='utf-8')
    client._verify_personal_profile()
    env = client._build_subprocess_env()
    assert Path(env["GEMINI_HOME"]).is_absolute()
    assert Path(env["GEMINI_HOME"]) / "antigravity-acp/settings.json" == profile


@pytest.mark.parametrize('roots', ['C:/task', [None], [''], ['missing-folder']])
def test_invalid_filesystem_roots_fail_before_session_request(workspace, roots):
    with pytest.raises(ValueError, match='filesystem_roots'):
        AntigravityACPClient(project_dir=str(workspace), filesystem_roots=roots)._session_parameters()


@pytest.mark.parametrize(("variant", "family", "effort"), [
    ("gemini-4-argon-low", "gemini-4-argon", "low"),
    ("gemini-4-argon-medium", "gemini-4-argon", "medium"),
    ("gemini-3.8-flash-high", "gemini-3.8-flash", "high"),
])
def test_legacy_gemini_variant_maps_to_family_and_effort(workspace, variant, family, effort):
    client = AntigravityACPClient(project_dir=str(workspace), model=variant)

    assert client.model == family
    assert client.config_reasoning_effort == effort


def test_personal_profile_accepts_only_personal_oauth(personal_profile, workspace):
    client = AntigravityACPClient(project_dir=str(workspace))
    client._verify_personal_profile()


@pytest.mark.parametrize("auth", [
    {}, {"type": "api-key"}, {"type": "oauth-enterprise"},
    {"type": "vertex-ai"}, {"type": "unknown"}, None, [],
])
def test_wrong_profile_is_rejected(personal_profile, workspace, auth):
    personal_profile.write_text(json.dumps({"auth": auth}), encoding="utf-8")
    client = AntigravityACPClient(project_dir=str(workspace))

    with pytest.raises(LLMBackendUnavailableError):
        client._verify_personal_profile()


@pytest.mark.parametrize("contents", ["{not-json", "[]", "null"])
def test_invalid_profile_is_rejected(personal_profile, workspace, contents):
    personal_profile.write_text(contents, encoding="utf-8")
    client = AntigravityACPClient(project_dir=str(workspace))

    with pytest.raises(LLMBackendUnavailableError):
        client._verify_personal_profile()


def test_missing_profile_does_not_use_general_cli_login(personal_profile, workspace):
    personal_profile.unlink()
    client = AntigravityACPClient(project_dir=str(workspace))

    with pytest.raises(LLMBackendUnavailableError):
        client._verify_personal_profile()


def test_subprocess_environment_cannot_switch_to_api_or_cloud(monkeypatch, workspace):
    blocked = {
        "GOOGLE_API_KEY": "synthetic-google-key",
        "GEMINI_API_KEY": "synthetic-gemini-key",
        "GOOGLE_APPLICATION_CREDENTIALS": "synthetic-credentials.json",
        "GOOGLE_CLOUD_PROJECT": "synthetic-project",
        "GOOGLE_CLOUD_QUOTA_PROJECT": "synthetic-quota-project",
        "GOOGLE_GENAI_USE_VERTEXAI": "true",
        "CLOUDSDK_AUTH_ACCESS_TOKEN": "synthetic-token",
        "AGY_AUTH_TYPE": "api-key",
        "ANTIGRAVITY_API_KEY": "synthetic-agy-key",
    }
    for key, value in blocked.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("AI_GOVERNESS_SYNTHETIC_CANARY", "keep")
    client = AntigravityACPClient(project_dir=str(workspace))

    child_env = client._build_subprocess_env()

    assert all(key not in child_env for key in blocked)
    assert child_env["AI_GOVERNESS_SYNTHETIC_CANARY"] == "keep"
    assert all(os.environ[key] == value for key, value in blocked.items())


def test_pro_tier_is_required_before_session_use(workspace):
    client = AntigravityACPClient(project_dir=str(workspace))
    client._validate_session_result(session_result())


@pytest.mark.parametrize("result", [
    {}, {"_meta": {}}, {"_meta": {"antigravity": {}}},
    {"_meta": []}, {"_meta": {"antigravity": []}},
    {"_meta": {"antigravity": {"tier": "g1-pro-tier"}}},
    session_result(tier="free-tier"),
    session_result(tier="standard-tier"),
    session_result(tier="g1-ultra-tier"),
])
def test_unknown_or_different_tier_is_rejected(workspace, result):
    client = AntigravityACPClient(project_dir=str(workspace))

    with pytest.raises(LLMBackendUnavailableError):
        client._validate_session_result(result)


@pytest.mark.asyncio
async def test_wrong_tier_session_never_sets_model_or_sends_prompt(workspace):
    client = AntigravityACPClient(project_dir=str(workspace), model="gemini-3.8-flash")
    client._send_request = AsyncMock(return_value={"result": session_result(tier="free-tier")})

    with pytest.raises(LLMBackendUnavailableError):
        await client._setup_session()

    assert [item.args[0] for item in client._send_request.await_args_list] == ["session/new"]
    assert client.session_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("restore_method", [None, "session/resume", "session/load"])
async def test_session_setup_restores_model_effort_yolo_and_mcp(workspace, restore_method):
    server = {"name": "synthetic-mcp", "command": "synthetic.exe", "args": [], "env": []}
    client = AntigravityACPClient(
        project_dir=str(workspace), model="gemini-3.8-flash", effort="low",
        mcp_servers=[server],
    )
    if restore_method:
        client.session_id = "synthetic-existing"
        client._agent_capabilities = (
            {"sessionCapabilities": {"resume": {}}}
            if restore_method == "session/resume" else {"loadSession": True}
        )
    options = session_result()["configOptions"]

    async def respond(method, params, **_kwargs):
        if method in {"session/new", "session/resume", "session/load"}:
            return {"result": session_result()}
        assert method == "session/set_config_option"
        changed = next(item for item in options if item["id"] == params["configId"])
        changed["currentValue"] = params["value"]
        return {"result": {"configOptions": deepcopy(options)}}

    client._send_request = AsyncMock(side_effect=respond)
    await client._setup_session()

    calls = client._send_request.await_args_list
    assert calls[0].args[0] == (restore_method or "session/new")
    assert calls[0].args[1]["cwd"] == str(workspace.resolve())
    assert server in calls[0].args[1]["mcpServers"]
    if restore_method:
        assert calls[0].args[1]["sessionId"] == "synthetic-existing"
    changes = {(item.args[1]["configId"], item.args[1]["value"]) for item in calls[1:]}
    assert changes == {("model", "gemini-3.8-flash"), ("thinking_level", "low"), ("mode", "yolo")}
    assert client.session_id == "synthetic-session"


@pytest.mark.asyncio
async def test_unavailable_model_has_no_silent_fallback(workspace):
    client = AntigravityACPClient(project_dir=str(workspace), model="gemini-missing")
    client._send_request = AsyncMock(return_value={"result": session_result()})

    with pytest.raises(RuntimeError, match="gemini-missing"):
        await client._setup_session()

    assert [item.args[0] for item in client._send_request.await_args_list] == ["session/new"]


def test_session_parameters_do_not_mutate_configured_mcp(workspace):
    servers = [{"name": "synthetic-mcp", "command": "synthetic.exe", "args": ["--test"], "env": []}]
    client = AntigravityACPClient(project_dir=str(workspace), mcp_servers=servers)
    params = client._session_parameters()
    next(item for item in params["mcpServers"] if item["name"] == "synthetic-mcp")["args"].append("mutated")

    assert servers[0]["args"] == ["--test"]
    assert next(item for item in client._session_parameters()["mcpServers"] if item["name"] == "synthetic-mcp")["args"] == ["--test"]


@pytest.mark.parametrize("kwargs", [
    {"auth_method": "api-key"}, {"auth_method": "oauth-enterprise"},
    {"subscription_only": False}, {"subscription_only": "false"},
    {"model": "claude-sonnet-5-5-low"}, {"model": "gpt-oss-120b-medium"},
    {"model": "gemini-4-argon-low", "effort": "high"},
])
def test_config_cannot_weaken_subscription_or_silently_change_model(workspace, kwargs):
    with pytest.raises(ValueError):
        AntigravityACPClient(project_dir=str(workspace), **kwargs)


def test_env_overrides_cannot_reintroduce_billing_route(workspace):
    client = AntigravityACPClient(project_dir=str(workspace), env_overrides={
        "GOOGLE_API_KEY": "synthetic-key", "GOOGLE_GENAI_USE_VERTEXAI": "true",
        "AGY_AUTH_TYPE": "api-key", "AI_GOVERNESS_SYNTHETIC_CANARY": "allowed",
    })
    child = client._build_subprocess_env()

    assert "GOOGLE_API_KEY" not in child
    assert "GOOGLE_GENAI_USE_VERTEXAI" not in child
    assert "AGY_AUTH_TYPE" not in child
    assert child["AI_GOVERNESS_SYNTHETIC_CANARY"] == "allowed"


@pytest.mark.asyncio
async def test_noninteractive_initialize_checks_profile_without_starting_oauth(personal_profile, workspace):
    client = AntigravityACPClient(project_dir=str(workspace))
    client._send_request = AsyncMock()

    await client._after_initialize({"authMethods": [{"id": "oauth-personal"}, {"id": "api-key"}]})

    client._send_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_initialize_cannot_choose_api_key_if_personal_unavailable(personal_profile, workspace):
    client = AntigravityACPClient(project_dir=str(workspace))
    client._send_request = AsyncMock()

    with pytest.raises(LLMBackendUnavailableError):
        await client._after_initialize({"authMethods": [{"id": "api-key"}]})

    client._send_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_login_only_requests_personal_oauth(workspace):
    client = AntigravityACPClient(project_dir=str(workspace))
    client._interactive_authentication = True
    client._send_request = AsyncMock(return_value={"result": session_result()})

    await client._after_initialize({"authMethods": [{"id": "oauth-personal"}, {"id": "api-key"}]})

    assert client._send_request.await_args.args == ("authenticate", {"methodId": "oauth-personal"})
    assert client.account_tier["id"] == "g1-pro-tier"


@pytest.mark.asyncio
async def test_explicit_login_resets_interactive_flag_after_failure(workspace):
    client = AntigravityACPClient(project_dir=str(workspace))
    client.ensure_ready = AsyncMock(side_effect=RuntimeError("synthetic-login-failure"))

    with pytest.raises(RuntimeError, match="synthetic-login-failure"):
        await client.authenticate_personal(timeout_seconds=1)

    assert client._interactive_authentication is False


def test_context_bootstrap_preserves_existing_private_utf8_files(personal_profile, workspace):
    existing = {name: (workspace / name).read_bytes() for name in ("AGENTS.md", "MEMORY.md")}
    client = AntigravityACPClient(project_dir=str(workspace))

    client._before_start()

    assert all((workspace / name).read_bytes() == content for name, content in existing.items())
    assert (workspace / "TOOLS.md").is_file()


def test_context_bootstrap_fills_only_missing_files(personal_profile, tmp_path):
    root = tmp_path / "fresh synthetic workspace"
    client = AntigravityACPClient(project_dir=str(root))

    client._before_start()

    assert (root / "AGENTS.md").is_file()
    assert (root / "MEMORY.md").is_file()
    assert (root / "AGENTS.md").read_text(encoding="utf-8").strip()


def test_context_missing_required_file_is_rejected(personal_profile, workspace):
    client = AntigravityACPClient(project_dir=str(workspace), required_context_files=["missing-required.md"])

    with pytest.raises(LLMBackendUnavailableError, match="missing-required.md"):
        client._before_start()


def test_context_is_reloaded_on_change_and_on_new_session(personal_profile, workspace):
    client = AntigravityACPClient(project_dir=str(workspace), instruction_files=[])
    client._validate_session_result(session_result())
    client.session_id = "synthetic-session"

    initial = json.dumps(client._build_prompt("first"), ensure_ascii=False)
    assert "SYNTHETIC_RULES_KEEP" in initial and "SYNTHETIC_MEMORY_COBALT" in initial
    client._prompt_completed({"result": {"stopReason": "end_turn"}})
    unchanged = json.dumps(client._build_prompt("second"), ensure_ascii=False)
    assert "SYNTHETIC_RULES_KEEP" not in unchanged and "SYNTHETIC_MEMORY_COBALT" not in unchanged

    (workspace / "MEMORY.md").write_text("SYNTHETIC_MEMORY_UPDATED", encoding="utf-8")
    changed = json.dumps(client._build_prompt("third"), ensure_ascii=False)
    assert "SYNTHETIC_MEMORY_UPDATED" in changed and "SYNTHETIC_RULES_KEEP" not in changed
    client._prompt_completed({"result": {"stopReason": "end_turn"}})
    client._validate_session_result(session_result(session_id="synthetic-new"))
    client.session_id = "synthetic-new"
    new_session = json.dumps(client._build_prompt("fourth"), ensure_ascii=False)
    assert "SYNTHETIC_RULES_KEEP" in new_session and "SYNTHETIC_MEMORY_UPDATED" in new_session


def test_unsuccessful_prompt_does_not_consume_context(personal_profile, workspace):
    client = AntigravityACPClient(project_dir=str(workspace), instruction_files=[])
    client._validate_session_result(session_result())
    client.session_id = "synthetic-session"

    client._build_prompt("first attempt")
    # A failed transport never calls _prompt_completed.
    retry = json.dumps(client._build_prompt("user retry"), ensure_ascii=False)

    assert "SYNTHETIC_RULES_KEEP" in retry and "SYNTHETIC_MEMORY_COBALT" in retry


@pytest.mark.asyncio
async def test_auth_change_between_turns_blocks_prompt_and_cleans_stream_state(personal_profile, workspace):
    client = AntigravityACPClient(project_dir=str(workspace))
    client.session_id = "synthetic-session"
    client.process = MagicMock(returncode=None)
    client._validate_session_result(session_result())
    client.ensure_ready = AsyncMock(return_value=True)
    client._send_request = AsyncMock()
    personal_profile.write_text(json.dumps({"auth": {"type": "api-key"}}), encoding="utf-8")

    with pytest.raises(LLMBackendUnavailableError):
        _ = [text async for text in client.send_message("must not be sent")]

    client._send_request.assert_not_awaited()
    assert client._streaming_queues == {}
    assert client._active_prompt_req_id is None
