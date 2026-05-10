import os
import shutil
import subprocess
import sys


def _emit(text: str | bytes | None, *, stream) -> None:
    if not text:
        return
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    print(text, end="", file=stream)


def main() -> int:
    model = os.environ.get("AI_GOVERNESS_GEMINI_AUTH_PROBE_MODEL", "gemini-2.5-flash-lite")
    timeout_seconds = float(os.environ.get("AI_GOVERNESS_GEMINI_AUTH_PROBE_TIMEOUT_SECONDS", "45"))
    gemini_path = (
        shutil.which("gemini.cmd")
        or shutil.which("gemini.exe")
        or shutil.which("gemini")
        or shutil.which("gemini.ps1")
    )
    if not gemini_path:
        print("[ERROR] Gemini CLI was not found on PATH.", file=sys.stderr)
        return 127

    if gemini_path.lower().endswith(".ps1"):
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", gemini_path]
    else:
        command = [gemini_path]

    command += [
        "-m",
        model,
        "-p",
        "Reply with exactly OK.",
        "--output-format",
        "json",
        "--skip-trust",
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        print("[ERROR] Gemini CLI was not found on PATH.", file=sys.stderr)
        return 127
    except subprocess.TimeoutExpired as exc:
        _emit(exc.stdout, stream=sys.stdout)
        _emit(exc.stderr, stream=sys.stderr)
        print(f"[ERROR] Gemini CLI auth probe timed out after {timeout_seconds:g} seconds.", file=sys.stderr)
        return 124

    if completed.returncode == 0:
        print("[OK] Gemini CLI headless auth check succeeded.")
        return 0

    _emit(completed.stdout, stream=sys.stdout)
    _emit(completed.stderr, stream=sys.stderr)
    print(f"[WARN] Gemini CLI headless auth check failed with exit code {completed.returncode}.", file=sys.stderr)
    return completed.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
