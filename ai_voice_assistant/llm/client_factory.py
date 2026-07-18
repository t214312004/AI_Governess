from .base_client import BaseLLMClient
from .claude_code_client import ClaudeCodeClient
from .codex_cli_client import CodexCLIClient
from .opencode_cli_client import OpenCodeCLIClient
from .grok_cli_client import GrokCLIClient
from .antigravity_cli_client import AntigravityCLIClient


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
        )
    if backend == "codex_cli":
        return CodexCLIClient(
            project_dir=kwargs.get("project_dir", "./"),
            model=kwargs.get("model"),
            reasoning_effort=kwargs.get("reasoning_effort", "low"),
            personality=kwargs.get("personality", "friendly"),
            sandbox=kwargs.get("sandbox", "workspace-write"),
            approval_policy=kwargs.get("approval_policy", "on-request"),
            request_timeout_seconds=kwargs.get("request_timeout_seconds", 30.0),
        )
    if backend == "opencode_cli":
        return OpenCodeCLIClient(
            project_dir=kwargs.get("project_dir", "./agent_workspace"),
            model=kwargs.get("model") or None,
            mode=kwargs.get("mode") or None,
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
        return AntigravityCLIClient(
            project_dir=kwargs.get("project_dir", "./agent_workspace"),
            print_timeout=kwargs.get("print_timeout", ""),
        )
    raise ValueError(f"未知的 LLM 後端：{backend}")
