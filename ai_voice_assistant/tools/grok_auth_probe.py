import asyncio
import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from config import config  # noqa: E402
from llm.grok_cli_client import GrokCLIClient  # noqa: E402


async def _run_probe(timeout_seconds: float) -> tuple[bool, str]:
    backend_config = config.get("llm", "grok_cli", default={}) or {}
    client = GrokCLIClient(
        project_dir=backend_config.get("project_dir", "./agent_workspace"),
        executable=backend_config.get("executable") or None,
        model=backend_config.get("model") or None,
        reasoning_effort=backend_config.get("reasoning_effort") or None,
        auth_method=backend_config.get("auth_method", "auto"),
        auto_approve=backend_config.get("auto_approve", True),
        auto_approve_scope=backend_config.get("auto_approve_scope", "once"),
        enable_web_search=backend_config.get("enable_web_search", True),
        enable_subagents=backend_config.get("enable_subagents", False),
        load_private_context=backend_config.get("load_private_context", True),
        required_context_files=backend_config.get("required_context_files", ["AGENTS.md"]),
        instruction_files=backend_config.get("instruction_files", ["MEMORY.md"]),
        request_timeout_seconds=backend_config.get("request_timeout_seconds", 30.0),
    )
    if not client._find_executable():
        return False, "Grok Build executable was not found"

    try:
        await asyncio.wait_for(client.ensure_ready(), timeout=timeout_seconds)
        return True, "Grok ACP initialize, authentication, and session setup succeeded"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        await client.aclose()


def main() -> int:
    try:
        timeout_seconds = float(
            os.environ.get("AI_GOVERNESS_GROK_AUTH_PROBE_TIMEOUT_SECONDS", "45")
        )
    except ValueError:
        timeout_seconds = 45.0

    ok, message = asyncio.run(_run_probe(timeout_seconds))
    if ok:
        print(f"[OK] {message}.")
        return 0

    print(f"[WARN] Grok ACP check failed: {message}", file=sys.stderr)
    print(
        "Run `%USERPROFILE%\\.grok\\bin\\grok.exe login`, then retry.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
