from .base_client import BaseLLMClient
from .claude_code_client import ClaudeCodeClient
from .codex_cli_client import CodexCLIClient
from .opencode_cli_client import OpenCodeCLIClient
from .grok_cli_client import GrokCLIClient
from .antigravity_acp_client import AntigravityACPClient


def create_llm_client(backend: str, **kwargs) -> BaseLLMClient:
    """
    Create an LLM client from configuration.

    Supported `backend` values:
    - `claude_code`
    - `codex_cli`
    - `opencode_cli`
    - `grok_cli`
    - `antigravity_cli`
    """
    if backend == "claude_code":
        return ClaudeCodeClient(
            model=kwargs.get("model", "sonnet"),
            max_turns=kwargs.get("max_turns", 3),
            project_dir=kwargs.get("project_dir", "./agent_workspace"),
            permission_mode=kwargs.get("permission_mode", "bypassPermissions"),
            allowed_tools=kwargs.get("allowed_tools", ""),
            tools=kwargs.get("tools", "default"),
            effort=kwargs.get("effort", ""),
        )
    if backend == "codex_cli":
        return CodexCLIClient(
            project_dir=kwargs.get("project_dir", "./"),
            model=kwargs.get("model"),
            reasoning_effort=kwargs.get("reasoning_effort", "low"),
            personality=kwargs.get("personality", "friendly"),
            sandbox=kwargs.get("sandbox", "danger-full-access"),
            approval_policy=kwargs.get("approval_policy", "never"),
            request_timeout_seconds=kwargs.get("request_timeout_seconds", 30.0),
        )
    if backend == "opencode_cli":
        return OpenCodeCLIClient(
            project_dir=kwargs.get("project_dir", "./agent_workspace"),
            model=kwargs.get("model") or None,
            mode=kwargs.get("mode") or None,
            reasoning_effort=kwargs.get("reasoning_effort") or None,
            permission_mode=kwargs.get("permission_mode", "yolo"),
            auto_approve=kwargs.get("auto_approve", True),
            use_runtime_config_content=kwargs.get("use_runtime_config_content", True),
            enable_web_search=kwargs.get("enable_web_search", False),
            required_context_files=kwargs.get("required_context_files", ["AGENTS.md"]),
            instruction_files=kwargs.get("instruction_files", ["MEMORY.md"]),
            shell=kwargs.get("shell") or None,
        )
    if backend == "grok_cli":
        return GrokCLIClient(
            project_dir=kwargs.get("project_dir", "./agent_workspace"),
            executable=kwargs.get("executable") or None,
            model=kwargs.get("model") or None,
            reasoning_effort=kwargs.get("reasoning_effort") or None,
            auth_method=kwargs.get("auth_method", "auto"),
            auto_approve=kwargs.get("auto_approve", True),
            auto_approve_scope=kwargs.get("auto_approve_scope", "once"),
            enable_web_search=kwargs.get("enable_web_search", True),
            enable_subagents=kwargs.get("enable_subagents", False),
            load_private_context=kwargs.get("load_private_context", True),
            required_context_files=kwargs.get("required_context_files", ["AGENTS.md"]),
            instruction_files=kwargs.get("instruction_files", ["MEMORY.md"]),
            request_timeout_seconds=kwargs.get("request_timeout_seconds", 30.0),
        )
    if backend == "antigravity_cli":
        return AntigravityACPClient(
            project_dir=kwargs.get("project_dir", "./agent_workspace"),
            executable=kwargs.get("executable") or None,
            model=kwargs.get("model", ""),
            effort=kwargs.get("effort", ""),
            mode=kwargs.get("mode", "yolo"),
            auth_method=kwargs.get("auth_method", "oauth-personal"),
            subscription_only=kwargs.get("subscription_only", True),
            auto_approve=kwargs.get("auto_approve", True),
            auto_approve_scope=kwargs.get("auto_approve_scope", "once"),
            stream_mode=kwargs.get("stream_mode", "final_segment"),
            startup_timeout_seconds=kwargs.get("startup_timeout_seconds", 90),
            request_timeout_seconds=kwargs.get("request_timeout_seconds", 120),
            required_context_files=kwargs.get("required_context_files"),
            instruction_files=kwargs.get("instruction_files"),
            mcp_servers=kwargs.get("mcp_servers"),
            filesystem_roots=kwargs.get("filesystem_roots"),
            load_private_context=kwargs.get("load_private_context", True),
        )
    raise ValueError(f"未知的 LLM 後端：{backend}")
