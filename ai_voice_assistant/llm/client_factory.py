from .base_client import BaseLLMClient
from .claude_code_client import ClaudeCodeClient
from .codex_cli_client import CodexCLIClient
from .gemini_cli_client import GeminiCLIClient
from .openclaw_client import OpenClawClient


def create_llm_client(backend: str, **kwargs) -> BaseLLMClient:
    """
    Create an LLM client from configuration.

    Supported `backend` values:
    - `openclaw`
    - `claude_code`
    - `codex_cli`
    - `gemini_cli`
    """
    if backend == "openclaw":
        return OpenClawClient(
            api_url=kwargs.get("api_url", "http://localhost:18789/v1/responses"),
            token=kwargs.get("token", ""),
            agent_id=kwargs.get("agent_id", ""),
            user=kwargs.get("user", "voice-assistant"),
            model=kwargs.get("model", "openclaw"),
            message_channel=kwargs.get("message_channel", ""),
            scopes=kwargs.get("scopes", ""),
            request_timeout_seconds=kwargs.get("request_timeout_seconds", 60.0),
        )
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
            sandbox=kwargs.get("sandbox", "danger-full-access"),
            approval_policy=kwargs.get("approval_policy", "never"),
        )
    if backend == "gemini_cli":
        return GeminiCLIClient(
            project_dir=kwargs.get("project_dir", "./"),
        )
    raise ValueError(f"未知的 LLM 後端：{backend}")
