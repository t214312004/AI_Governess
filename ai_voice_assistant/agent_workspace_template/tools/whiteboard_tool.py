from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _resolve_app_dir() -> Path:
    env_path = os.environ.get("AI_GOVERNESS_APP_DIR")
    if env_path:
        return Path(env_path).resolve()
    return Path(__file__).resolve().parents[2]


APP_DIR = _resolve_app_dir()
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.whiteboard_manager import (  # noqa: E402
    DEFAULT_MAX_IMAGE_BYTES,
    DEFAULT_MAX_IMAGE_PIXELS,
    DEFAULT_MAX_MARKDOWN_BYTES,
    WhiteboardManager,
)


def _safe_result(status: str, operation: str, message: str, *, errors=None):
    return {
        "status": status,
        "operation": operation,
        "content_id": None,
        "content_type": None,
        "message_for_user": message,
        "errors": errors or [],
        "warnings": [],
    }


def _print_json(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _payload_root() -> Path:
    configured = os.environ.get("AI_GOVERNESS_WHITEBOARD_PAYLOAD_DIR")
    if configured:
        root = Path(configured)
    else:
        root = APP_DIR / "agent_workspace" / "tool_payloads" / "whiteboard"
    return root.resolve()


def _manager() -> WhiteboardManager:
    state_dir = os.environ.get("AI_GOVERNESS_WHITEBOARD_STATE_DIR", "whiteboard_state")
    return WhiteboardManager(
        APP_DIR,
        state_dir=state_dir,
        payload_root=_payload_root(),
        max_markdown_bytes=_int_env("AI_GOVERNESS_WHITEBOARD_MAX_MARKDOWN_BYTES", DEFAULT_MAX_MARKDOWN_BYTES),
        max_image_bytes=_int_env("AI_GOVERNESS_WHITEBOARD_MAX_IMAGE_BYTES", DEFAULT_MAX_IMAGE_BYTES),
        max_image_pixels=_int_env("AI_GOVERNESS_WHITEBOARD_MAX_IMAGE_PIXELS", DEFAULT_MAX_IMAGE_PIXELS),
    )


def _load_payload(path_text: str) -> dict:
    raw_path = Path(path_text)
    path = raw_path if raw_path.is_absolute() else (Path.cwd() / raw_path)
    path = path.resolve()
    root = _payload_root()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Payload must be under {root}") from exc
    with open(path, "r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Payload JSON must be an object.")
    return payload


def _payload_or_error(args, operation: str):
    try:
        return _load_payload(args.payload), None
    except Exception as exc:
        return None, _safe_result(
            "needs_clarification",
            operation,
            "白板工具讀不到有效的 payload，請重新產生工具輸入。",
            errors=[str(exc)],
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Governess whiteboard tool")
    subparsers = parser.add_subparsers(dest="action", required=True)

    markdown = subparsers.add_parser("show-markdown")
    markdown.add_argument("--payload", required=True)

    image = subparsers.add_parser("show-image")
    image.add_argument("--payload", required=True)

    close = subparsers.add_parser("close")
    close.add_argument("--content-id", default="")

    subparsers.add_parser("status")

    get_content = subparsers.add_parser("get-content")
    get_content.add_argument("--content-id", default="")
    get_content.add_argument("--max-chars", type=int, default=4000)

    return parser


def run(argv: list[str] | None = None) -> dict:
    args = build_parser().parse_args(argv)
    manager = _manager()

    if args.action == "show-markdown":
        payload, error = _payload_or_error(args, "show_markdown")
        return error or manager.show_markdown(payload)
    if args.action == "show-image":
        payload, error = _payload_or_error(args, "show_image")
        return error or manager.show_image(payload)
    if args.action == "close":
        return manager.close(args.content_id or None)
    if args.action == "status":
        return manager.status()
    if args.action == "get-content":
        return manager.get_content(args.content_id or None, max_chars=args.max_chars)
    return _safe_result("error", args.action, "Unsupported whiteboard tool action.")


def main(argv: list[str] | None = None) -> int:
    try:
        _print_json(run(argv))
        return 0
    except Exception as exc:
        _print_json(
            _safe_result(
                "error",
                "whiteboard_tool",
                "白板工具發生錯誤，沒有建立或更動白板。",
                errors=[f"{type(exc).__name__}: {exc}"],
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
