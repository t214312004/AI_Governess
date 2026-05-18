import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path


AUTH_COMPUTE_ADC = "compute-default-credentials"
AUTH_GATEWAY = "gateway"
AUTH_GEMINI_API_KEY = "gemini-api-key"
AUTH_OAUTH_PERSONAL = "oauth-personal"
AUTH_VERTEX_AI = "vertex-ai"


def _emit(text: str | bytes | None, *, stream) -> None:
    if not text:
        return
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    print(text, end="", file=stream)


def _load_json(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[WARN] Could not read {path}: {exc}", file=sys.stderr)
        return None
    if isinstance(data, dict):
        return data
    return None


def _find_gemini() -> str | None:
    return (
        shutil.which("gemini.cmd")
        or shutil.which("gemini.exe")
        or shutil.which("gemini")
        or shutil.which("gemini.ps1")
    )


def _selected_auth_type(home: Path) -> str | None:
    settings = _load_json(home / ".gemini" / "settings.json") or {}
    selected = settings.get("security", {}).get("auth", {}).get("selectedType")
    if isinstance(selected, str) and selected.strip():
        return selected.strip()
    return None


def _active_google_account(home: Path) -> str | None:
    accounts = _load_json(home / ".gemini" / "google_accounts.json") or {}
    active = accounts.get("active")
    if isinstance(active, str) and active.strip():
        return active.strip()
    return None


def _oauth_credentials_status(home: Path, now_ms: int | None = None) -> tuple[bool, str]:
    creds = _load_json(home / ".gemini" / "oauth_creds.json")
    if not creds:
        encrypted_store = home / ".gemini" / "gemini-credentials.json"
        if encrypted_store.exists():
            return True, "encrypted OAuth credential store exists"
        return False, "OAuth credential file was not found"

    refresh_token = creds.get("refresh_token")
    access_token = creds.get("access_token")
    expiry_date = creds.get("expiry_date")
    cred_type = creds.get("type")

    if cred_type in {"external_account_authorized_user", "service_account"}:
        return True, f"{cred_type} credentials found"

    if isinstance(refresh_token, str) and refresh_token.strip():
        account = _active_google_account(home)
        suffix = f" for {account}" if account else ""
        return True, f"cached OAuth refresh token found{suffix}"

    if isinstance(access_token, str) and access_token.strip():
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        if isinstance(expiry_date, (int, float)) and expiry_date > now_ms + 60_000:
            return True, "cached OAuth access token is still valid"
        return False, "OAuth access token is expired and no refresh token was found"

    return False, "OAuth credentials do not contain a usable token"


def _local_auth_status(home: Path) -> tuple[bool | None, str]:
    selected_auth = _selected_auth_type(home)

    if os.environ.get("GEMINI_API_KEY"):
        return True, "GEMINI_API_KEY is set"

    if os.environ.get("GOOGLE_GENAI_USE_GCA") == "true":
        return _oauth_credentials_status(home)

    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") == "true":
        if os.environ.get("GOOGLE_API_KEY"):
            return True, "GOOGLE_API_KEY is set for Vertex AI"
        if os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT_ID"):
            return True, "Google Cloud project is set for Vertex AI"
        return None, "Vertex AI auth is selected but required environment variables are not visible"

    if os.environ.get("GEMINI_CLI_USE_COMPUTE_ADC") == "true" or os.environ.get("CLOUD_SHELL") == "true":
        return None, "Application Default Credentials need a CLI handshake to verify"

    if selected_auth == AUTH_OAUTH_PERSONAL or selected_auth is None:
        return _oauth_credentials_status(home)

    if selected_auth == AUTH_GEMINI_API_KEY:
        return None, "Gemini API key may be stored in Gemini CLI credential storage"

    if selected_auth in {AUTH_VERTEX_AI, AUTH_COMPUTE_ADC, AUTH_GATEWAY}:
        return None, f"{selected_auth} auth needs a CLI handshake to verify"

    return None, f"unknown Gemini auth type: {selected_auth}"


def _terminate_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return

    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()


def _reader(stream, output_queue: queue.Queue) -> None:
    try:
        for line in stream:
            output_queue.put(line)
    except Exception as exc:  # pragma: no cover - defensive subprocess IO guard
        output_queue.put(f"[reader error] {exc}\n")


def _run_acp_probe(gemini_path: str, *, cwd: Path, timeout_seconds: float) -> tuple[bool, str]:
    if gemini_path.lower().endswith(".ps1"):
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", gemini_path]
    else:
        command = [gemini_path]
    command += ["--acp", "--yolo"]

    env = os.environ.copy()
    env["NO_BROWSER"] = "true"

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags,
    )

    stdout_queue: queue.Queue[str] = queue.Queue()
    stderr_queue: queue.Queue[str] = queue.Queue()
    threading.Thread(target=_reader, args=(process.stdout, stdout_queue), daemon=True).start()
    threading.Thread(target=_reader, args=(process.stderr, stderr_queue), daemon=True).start()

    responses: dict[int, dict] = {}
    stderr_lines: list[str] = []

    def drain() -> None:
        while True:
            try:
                line = stdout_queue.get_nowait().strip()
            except queue.Empty:
                break
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and isinstance(data.get("id"), int):
                responses[data["id"]] = data

        while True:
            try:
                line = stderr_queue.get_nowait().strip()
            except queue.Empty:
                break
            if line:
                stderr_lines.append(line)

    def send_request(req_id: int, method: str, params: dict) -> None:
        assert process.stdin is not None
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": req_id}
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def wait_for(req_id: int) -> dict:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                drain()
                detail = stderr_lines[-1] if stderr_lines else f"process exited with code {process.returncode}"
                raise RuntimeError(detail)
            drain()
            if req_id in responses:
                return responses[req_id]
            time.sleep(0.05)
        raise TimeoutError(f"timed out waiting for ACP response id {req_id}")

    try:
        send_request(1, "initialize", {"protocolVersion": 0})
        init_resp = wait_for(1)
        if "error" in init_resp:
            return False, f"ACP initialize failed: {init_resp['error']}"

        send_request(2, "session/new", {"cwd": str(cwd), "mcpServers": []})
        session_resp = wait_for(2)
        if "error" in session_resp:
            return False, f"ACP session setup failed: {session_resp['error']}"
        if session_resp.get("result", {}).get("sessionId"):
            return True, "ACP session setup succeeded"
        return False, "ACP session setup did not return a sessionId"
    except Exception as exc:
        drain()
        details = f"{exc}"
        if stderr_lines:
            details = f"{details}; stderr: {stderr_lines[-1]}"
        return False, details
    finally:
        _terminate_process_tree(process)


def main() -> int:
    timeout_seconds = float(os.environ.get("AI_GOVERNESS_GEMINI_AUTH_PROBE_TIMEOUT_SECONDS", "20"))
    gemini_path = _find_gemini()
    if not gemini_path:
        print("[ERROR] Gemini CLI was not found on PATH.", file=sys.stderr)
        return 127

    home = Path.home()
    local_ok, local_message = _local_auth_status(home)
    if local_ok is True:
        print(f"[OK] Gemini CLI auth state found: {local_message}.")
        return 0
    if local_ok is False:
        print(f"[WARN] Gemini CLI local auth check failed: {local_message}.", file=sys.stderr)
        return 1

    print(f"[INFO] Gemini CLI local auth check is inconclusive: {local_message}.")
    print("[INFO] Verifying Gemini CLI auth via ACP handshake...")

    ok, message = _run_acp_probe(gemini_path, cwd=Path.cwd(), timeout_seconds=timeout_seconds)
    if ok:
        print(f"[OK] Gemini CLI ACP auth check succeeded: {message}.")
        return 0

    print(f"[WARN] Gemini CLI ACP auth check failed: {message}.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
