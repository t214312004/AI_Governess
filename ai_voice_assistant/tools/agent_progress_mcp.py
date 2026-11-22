"""Accept user-facing progress over MCP stdio for the current app turn."""

import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from time import monotonic


_MESSAGE_LIMIT = 64 * 1024
_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
_TOOL = {
    "name": "report_progress",
    "description": "Submit a user-visible progress update about the active task.",
    "inputSchema": {
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1}},
        "required": ["text"],
        "additionalProperties": False,
    },
}


def write_record(path: Path, record: dict):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        staged = Path(handle.name)
    try:
        staged.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def report_path(mailbox: Path, turn: str, slot: int) -> Path:
    return mailbox.with_name(f"{mailbox.name}-{turn}-{slot}.json")


def save_progress(mailbox: Path, text: str):
    reported_at = monotonic()
    active = json.loads(mailbox.read_text(encoding="utf-8"))
    turn = active["turn"]
    started_at, interval = active["started_at"], active["interval"]
    if not re.fullmatch(r"[0-9a-f]{32}", turn) or reported_at < started_at or interval <= 0:
        raise ValueError("Invalid active turn")
    slot = max(1, math.ceil((reported_at - started_at) / interval))
    write_record(report_path(mailbox, turn, slot), {"text": text})


def _tool_result(message: str, *, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": error}


def handle_request(mailbox: Path, request) -> dict | None:
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return _error(None, -32600, "Invalid request")
    if "id" not in request:
        return None
    request_id = request["id"]
    params = request.get("params", {})
    if not isinstance(params, dict):
        return _error(request_id, -32602, "Invalid params")
    method = request.get("method")
    if method == "initialize":
        version = params.get("protocolVersion")
        result = {
            "protocolVersion": version if version in _VERSIONS else _VERSIONS[-1],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ai-governess-progress", "version": "1.0.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [_TOOL]}
    elif method == "tools/call":
        arguments = params.get("arguments")
        if params.get("name") != _TOOL["name"]:
            return _error(request_id, -32602, "Unknown tool")
        text = arguments.get("text") if isinstance(arguments, dict) and arguments.keys() == {"text"} else None
        if not isinstance(text, str) or not text.strip():
            return _error(request_id, -32602, "Expected non-empty progress text")
        try:
            save_progress(mailbox, text)
        except (OSError, KeyError, TypeError, ValueError, OverflowError):
            result = _tool_result("No active progress receiver.", error=True)
        else:
            result = _tool_result("Progress received.")
    else:
        return _error(request_id, -32601, "Method not found")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def main(mailbox: Path) -> int:
    while line := sys.stdin.buffer.readline(_MESSAGE_LIMIT + 1):
        if len(line) > _MESSAGE_LIMIT:
            return 2
        try:
            request = json.loads(line.decode("utf-8"))
        except (ValueError, RecursionError):
            response = _error(None, -32700, "Parse error")
        else:
            response = handle_request(mailbox, request)
        if response is not None:
            sys.stdout.buffer.write(json.dumps(response).encode("utf-8") + b"\n")
            sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
