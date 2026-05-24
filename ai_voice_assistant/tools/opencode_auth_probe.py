import asyncio
import shutil
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from config import config  # noqa: E402
from llm.opencode_cli_client import OpenCodeCLIClient  # noqa: E402


def _find_opencode() -> str | None:
    return (
        shutil.which("opencode.cmd")
        or shutil.which("opencode.exe")
        or shutil.which("opencode")
    )


async def _run_probe(timeout_seconds: float) -> tuple[bool, str]:
    backend_config = config.get("llm", "opencode_cli", default={}) or {}
    client = OpenCodeCLIClient(
        project_dir=backend_config.get("project_dir", "./agent_workspace"),
        model=backend_config.get("model") or None,
        mode=backend_config.get("mode") or None,
        permission_mode=backend_config.get("permission_mode", "yolo"),
        auto_approve=backend_config.get("auto_approve", True),
        use_runtime_config_content=backend_config.get("use_runtime_config_content", True),
        enable_web_search=backend_config.get("enable_web_search", False),
        required_context_files=backend_config.get("required_context_files", ["AGENTS.md"]),
        instruction_files=backend_config.get("instruction_files", ["MEMORY.md"]),
        shell=backend_config.get("shell") or None,
    )
    try:
        await asyncio.wait_for(client.ensure_ready(), timeout=timeout_seconds)
        return True, "OpenCode ACP initialize and session setup succeeded"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        await client.aclose()


def main() -> int:
    if not _find_opencode():
        print("[ERROR] OpenCode CLI was not found on PATH.", file=sys.stderr)
        print("Install it first, then run: opencode", file=sys.stderr)
        return 127

    timeout_seconds = 30.0
    try:
        import os

        timeout_seconds = float(
            os.environ.get("AI_GOVERNESS_OPENCODE_AUTH_PROBE_TIMEOUT_SECONDS", "30")
        )
    except ValueError:
        timeout_seconds = 30.0

    ok, message = asyncio.run(_run_probe(timeout_seconds))
    if ok:
        print(f"[OK] {message}.")
        return 0

    print(f"[WARN] OpenCode ACP check failed: {message}", file=sys.stderr)
    print("Open OpenCode manually with `opencode` and finish login, then retry.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
