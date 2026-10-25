"""Synthetic Antigravity smoke diagnostic using the production ACP client.

No private application config or workspace is read. Without --smoke this only
prepares a verified Google AI Pro session. --authenticate explicitly permits
the official personal Google OAuth flow. Output excludes session IDs, response
text, credentials, thoughts and tool payloads.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai_voice_assistant"))

from llm.antigravity_acp_client import AntigravityACPClient
from llm.base_client import STREAM_ACTIVITY_KEEPALIVE


async def run_probe(args):
    with tempfile.TemporaryDirectory(prefix="governess-acp-smoke-") as raw_workspace:
        workspace = Path(raw_workspace)
        (workspace / "AGENTS.md").write_text(
            "# Synthetic smoke rules\nUse Traditional Chinese unless a test requests an exact marker.\n",
            encoding="utf-8",
        )
        (workspace / "MEMORY.md").write_text(
            "# Synthetic memory\nThe synthetic smoke color is cobalt.\n",
            encoding="utf-8",
        )
        client = AntigravityACPClient(
            project_dir=str(workspace),
            executable=args.executable,
            model=args.model,
            effort=args.effort,
        )
        summary = {"transport": "official-acp", "synthetic_workspace": True}
        started = time.monotonic()
        try:
            if args.authenticate:
                await client.authenticate_personal(timeout_seconds=300)
            await client.ensure_ready()
            summary.update(
                ready=True,
                setup_seconds=round(time.monotonic() - started, 3),
                model=client.model,
                effort=client.config_reasoning_effort,
                mode=client.mode,
            )
            if args.smoke:
                turn_started = time.monotonic()
                chunks = [
                    text
                    async for text in client.send_message(
                        "Read MEMORY.md. If the synthetic smoke color is cobalt, "
                        "reply exactly ACP_SMOKE_OK. Otherwise reply ACP_SMOKE_FAILED."
                    )
                    if text != STREAM_ACTIVITY_KEEPALIVE
                ]
                summary["smoke_passed"] = "".join(chunks).strip() == "ACP_SMOKE_OK"
                summary["turn_seconds"] = round(time.monotonic() - turn_started, 3)
                if not summary["smoke_passed"]:
                    raise RuntimeError("Synthetic response marker did not match")
            return summary
        finally:
            await client.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", default="", help="Official server path; blank uses the managed runtime")
    parser.add_argument("--model", default="", help="Gemini family or supported legacy Gemini variant")
    parser.add_argument("--effort", default="", help="Requested supported thinking level")
    parser.add_argument("--authenticate", action="store_true", help="Explicitly allow personal Google OAuth login")
    parser.add_argument("--smoke", action="store_true", help="Consume a small amount of subscription quota for a synthetic turn")
    args = parser.parse_args()
    try:
        summary = asyncio.run(run_probe(args))
    except Exception as exc:
        # Error messages may contain provider details; emit only the error class.
        print(json.dumps({"ready": False, "error_type": type(exc).__name__}))
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
