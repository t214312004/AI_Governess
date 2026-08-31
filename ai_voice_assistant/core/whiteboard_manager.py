from __future__ import annotations

import contextlib
import html
import json
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - supported Python versions include zoneinfo.
    ZoneInfo = None

from core.schedule_models import DEFAULT_TIMEZONE


SCHEMA_VERSION = 1
DEFAULT_MAX_MARKDOWN_BYTES = 200000
DEFAULT_MAX_IMAGE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_IMAGE_PIXELS = 16_000_000
DEFAULT_GET_CONTENT_CHARS = 4000
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class WhiteboardValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        user_message: str | None = None,
    ):
        super().__init__(message)
        self.field = field
        self.user_message = user_message or message


class _StateFileLock:
    def __init__(self, path: Path):
        self.path = path
        self._handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "a+b")
        if self._handle.seek(0, os.SEEK_END) == 0:
            self._handle.write(b"0")
            self._handle.flush()
        if os.name == "nt":
            import msvcrt

            self._handle.seek(0)
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_LOCK, 1)
        else:  # pragma: no cover - CI for this repo is normally Windows.
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


class WhiteboardManager:
    """Owns durable whiteboard state and materialized display assets."""

    _markdown_image_pattern = re.compile(r"!\[[^\]]*\]\([^)]+\)")
    _markdown_link_pattern = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
    _url_scheme_pattern = re.compile(r"\b(https?|file)://", re.IGNORECASE)
    _html_tag_pattern = re.compile(r"<[^>\n]+>")

    def __init__(
        self,
        app_dir: str | os.PathLike[str],
        *,
        state_dir: str | os.PathLike[str] = "whiteboard_state",
        payload_root: str | os.PathLike[str] | None = None,
        max_markdown_bytes: int = DEFAULT_MAX_MARKDOWN_BYTES,
        max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
        max_image_pixels: int = DEFAULT_MAX_IMAGE_PIXELS,
        now_func=None,
    ):
        self.app_dir = Path(app_dir).resolve()

        state_path = Path(state_dir)
        if not state_path.is_absolute():
            state_path = self.app_dir / state_path
        self.state_dir = state_path.resolve()

        payload_path = Path(payload_root) if payload_root else self.app_dir / "agent_workspace" / "tool_payloads" / "whiteboard"
        if not payload_path.is_absolute():
            payload_path = self.app_dir / payload_path
        self.payload_root = payload_path.resolve()

        self.assets_dir = self.state_dir / "assets"
        self.active_path = self.state_dir / "active.json"
        self._lock_path = self.state_dir / ".whiteboard.lock"
        self.max_markdown_bytes = max(1, int(max_markdown_bytes or DEFAULT_MAX_MARKDOWN_BYTES))
        self.max_image_bytes = max(1, int(max_image_bytes or DEFAULT_MAX_IMAGE_BYTES))
        self.max_image_pixels = max(1, int(max_image_pixels or DEFAULT_MAX_IMAGE_PIXELS))
        self._now_func = now_func
        self.ensure_directories()

    def ensure_directories(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.payload_root.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        with _StateFileLock(self._lock_path):
            yield

    def now(self) -> datetime:
        if self._now_func is not None:
            value = self._now_func()
            if value.tzinfo is None:
                return value.replace(tzinfo=self._get_timezone(DEFAULT_TIMEZONE))
            return value
        return datetime.now(self._get_timezone(DEFAULT_TIMEZONE))

    @staticmethod
    def _get_timezone(name: str):
        if ZoneInfo is not None:
            try:
                return ZoneInfo(name)
            except Exception:
                pass
        return None

    def _result(
        self,
        status: str,
        *,
        operation: str,
        message_for_user: str | None = None,
        content_id: str | None = None,
        content_type: str | None = None,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
        **extra,
    ) -> dict[str, Any]:
        result = {
            "status": status,
            "operation": operation,
            "content_id": content_id,
            "content_type": content_type,
            "message_for_user": message_for_user,
            "errors": errors or [],
            "warnings": warnings or [],
        }
        result.update(extra)
        return result

    def _validation_result(self, exc: WhiteboardValidationError, *, operation: str) -> dict[str, Any]:
        return self._result(
            "needs_clarification",
            operation=operation,
            message_for_user=exc.user_message,
            errors=[str(exc)],
            field=exc.field,
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("JSON file must contain an object.")
        return data

    @staticmethod
    def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            if text and not text.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)

    def _new_content_id(self, now: datetime | None = None) -> str:
        stamp = (now or self.now()).strftime("%Y%m%d_%H%M%S")
        return f"wb_{stamp}_{uuid.uuid4().hex[:6]}"

    @staticmethod
    def _clean_title(value: Any) -> str:
        title = " ".join(str(value or "").strip().split())
        return title[:80] if title else "白板"

    def _resolve_payload_file(self, value: Any, *, field: str) -> Path:
        path_text = str(value or "").strip()
        if not path_text:
            raise WhiteboardValidationError(
                f"Missing {field}.",
                field=field,
                user_message="白板工具缺少必要的檔案路徑。",
            )
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", path_text):
            raise WhiteboardValidationError(
                f"{field} must be a local payload file, not a URL.",
                field=field,
                user_message="白板工具只能讀取 payload 目錄內的本機檔案。",
            )

        raw_path = Path(path_text)
        path = raw_path if raw_path.is_absolute() else Path.cwd() / raw_path
        path = path.resolve()
        root = self.payload_root.resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise WhiteboardValidationError(
                f"{field} must be under {root}",
                field=field,
                user_message="白板工具只能讀取 tool_payloads/whiteboard 底下的檔案。",
            ) from exc
        if not path.exists() or not path.is_file():
            raise WhiteboardValidationError(
                f"{field} does not exist: {path}",
                field=field,
                user_message="白板工具找不到指定的檔案。",
            )
        return path

    def _load_markdown(self, payload: dict[str, Any]) -> str:
        has_inline = "markdown" in payload and payload.get("markdown") is not None
        has_path = bool(str(payload.get("markdown_path") or "").strip())
        if has_inline == has_path:
            raise WhiteboardValidationError(
                "Provide exactly one of markdown or markdown_path.",
                field="markdown",
                user_message="白板文字需要提供 markdown 或 markdown_path 其中一種。",
            )
        if has_inline:
            markdown = payload.get("markdown")
            if not isinstance(markdown, str):
                raise WhiteboardValidationError(
                    "markdown must be a string.",
                    field="markdown",
                    user_message="白板 Markdown 內容格式不正確。",
                )
            data = markdown.encode("utf-8")
        else:
            path = self._resolve_payload_file(payload.get("markdown_path"), field="markdown_path")
            data = path.read_bytes()
            try:
                markdown = data.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise WhiteboardValidationError(
                    "markdown_path must be strict UTF-8.",
                    field="markdown_path",
                    user_message="白板 Markdown 檔案必須是 UTF-8 文字。",
                ) from exc

        if len(data) > self.max_markdown_bytes:
            raise WhiteboardValidationError(
                f"Markdown is too large: {len(data)} bytes.",
                field="markdown",
                user_message="白板 Markdown 內容太大，請縮短後再顯示。",
            )
        return markdown

    def _sanitize_markdown(self, markdown: str) -> tuple[str, list[str]]:
        warnings: list[str] = []
        if self._markdown_image_pattern.search(markdown):
            raise WhiteboardValidationError(
                "Markdown image syntax is not allowed.",
                field="markdown",
                user_message="白板文字模式不支援 Markdown 圖片，請改用 show-image。",
            )

        def replace_link(match: re.Match) -> str:
            warnings.append("Markdown links were converted to plain text.")
            return match.group(1)

        sanitized = self._markdown_link_pattern.sub(replace_link, markdown)

        if self._url_scheme_pattern.search(sanitized):
            warnings.append("URL schemes were neutralized in Markdown text.")
            sanitized = self._url_scheme_pattern.sub(lambda m: f"{m.group(1)}[:]//", sanitized)

        if self._html_tag_pattern.search(sanitized):
            warnings.append("Raw HTML-like tags were escaped.")
            sanitized = sanitized.replace("<", html.escape("<")).replace(">", html.escape(">"))

        return sanitized, warnings

    def _copy_validated_image(self, payload: dict[str, Any], asset_dir: Path) -> dict[str, Any]:
        source_path = self._resolve_payload_file(payload.get("image_path"), field="image_path")
        extension = source_path.suffix.lower()
        if extension not in ALLOWED_IMAGE_EXTENSIONS:
            raise WhiteboardValidationError(
                f"Unsupported image extension: {extension}",
                field="image_path",
                user_message="白板圖片只支援 PNG、JPG、WEBP 或 GIF。",
            )

        image_bytes = source_path.stat().st_size
        if image_bytes > self.max_image_bytes:
            raise WhiteboardValidationError(
                f"Image is too large: {image_bytes} bytes.",
                field="image_path",
                user_message="白板圖片太大，請縮小後再顯示。",
            )

        try:
            from PIL import Image

            with Image.open(source_path) as image:
                width, height = image.size
                image_format = image.format or extension.lstrip(".").upper()
                image.verify()
        except Exception as exc:
            raise WhiteboardValidationError(
                f"Invalid image file: {source_path.name}",
                field="image_path",
                user_message="白板工具讀不到有效的圖片檔案。",
            ) from exc

        pixels = int(width) * int(height)
        if pixels > self.max_image_pixels:
            raise WhiteboardValidationError(
                f"Image dimensions are too large: {width}x{height}.",
                field="image_path",
                user_message="白板圖片解析度太大，請縮小後再顯示。",
            )

        asset_dir.mkdir(parents=True, exist_ok=True)
        target_path = asset_dir / f"image{extension}"
        shutil.copy2(source_path, target_path)
        return {
            "image_path": self._to_state_path(target_path),
            "image_basename": target_path.name,
            "image_format": image_format,
            "image_bytes": image_bytes,
            "width": int(width),
            "height": int(height),
            "alt_text": " ".join(str(payload.get("alt_text") or "").strip().split())[:500],
        }

    def _to_state_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.app_dir).as_posix()
        except ValueError:
            return str(path.resolve())

    def _resolve_state_path(self, path_text: str | None) -> Path | None:
        if not path_text:
            return None
        raw_path = Path(path_text)
        path = raw_path if raw_path.is_absolute() else self.app_dir / raw_path
        return path.resolve()

    def resolve_asset_path(self, path_text: str | None) -> Path | None:
        path = self._resolve_state_path(path_text)
        if path is None:
            return None
        assets_root = self.assets_dir.resolve()
        try:
            path.relative_to(assets_root)
        except ValueError:
            return None
        if path == assets_root:
            return None
        return path

    def _asset_dir_from_state(self, active: dict[str, Any] | None) -> Path | None:
        if not active:
            return None
        asset_dir_text = active.get("asset_dir")
        path = self._resolve_state_path(asset_dir_text) if asset_dir_text else None
        if path is None:
            content_id = str(active.get("content_id") or "").strip()
            if not content_id:
                return None
            path = (self.assets_dir / content_id).resolve()

        assets_root = self.assets_dir.resolve()
        try:
            path.relative_to(assets_root)
        except ValueError:
            return None
        if path == assets_root:
            return None
        return path

    def _delete_asset_dir_for_state(self, active: dict[str, Any] | None) -> bool:
        asset_dir = self._asset_dir_from_state(active)
        if asset_dir is None or not asset_dir.exists():
            return False
        if not asset_dir.is_dir():
            return False
        shutil.rmtree(asset_dir)
        return True

    def _active_from_disk(self) -> dict[str, Any] | None:
        if not self.active_path.exists():
            return None
        try:
            active = self._read_json(self.active_path)
        except Exception:
            return None
        if not isinstance(active, dict) or not active.get("content_id"):
            return None
        return active

    def _write_active(self, active: dict[str, Any]) -> None:
        self._atomic_write_json(self.active_path, active)

    def show_markdown(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            if not isinstance(payload, dict):
                raise WhiteboardValidationError(
                    "Payload must be an object.",
                    user_message="白板工具需要 JSON object payload。",
                )
            markdown = self._load_markdown(payload)
            sanitized, warnings = self._sanitize_markdown(markdown)
        except WhiteboardValidationError as exc:
            return self._validation_result(exc, operation="show_markdown")

        now = self.now()
        content_id = self._new_content_id(now)
        asset_dir = self.assets_dir / content_id
        content_path = asset_dir / "content.md"
        self._atomic_write_text(content_path, sanitized)

        active = {
            "version": SCHEMA_VERSION,
            "revision": uuid.uuid4().hex,
            "content_id": content_id,
            "content_type": "markdown",
            "title": self._clean_title(payload.get("title")),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "source": "tool",
            "renderer": "ctk_markdown",
            "markdown_path": self._to_state_path(content_path),
            "asset_dir": self._to_state_path(asset_dir),
            "display_only": True,
            "sanitizer": {
                "raw_html": "escaped",
                "external_links": "plain_text",
                "markdown_images": "blocked",
            },
            "expires_at": payload.get("expires_at"),
        }

        with self._locked():
            previous_active = self._active_from_disk()
            self._write_active(active)
            self._delete_asset_dir_for_state(previous_active)

        return self._result(
            "shown",
            operation="show_markdown",
            content_id=content_id,
            content_type="markdown",
            message_for_user="已顯示白板。",
            warnings=warnings,
            title=active["title"],
        )

    def show_image(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            if not isinstance(payload, dict):
                raise WhiteboardValidationError(
                    "Payload must be an object.",
                    user_message="白板工具需要 JSON object payload。",
                )
            now = self.now()
            content_id = self._new_content_id(now)
            asset_dir = self.assets_dir / content_id
            image_info = self._copy_validated_image(payload, asset_dir)
        except WhiteboardValidationError as exc:
            return self._validation_result(exc, operation="show_image")

        active = {
            "version": SCHEMA_VERSION,
            "revision": uuid.uuid4().hex,
            "content_id": content_id,
            "content_type": "image",
            "title": self._clean_title(payload.get("title")),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "source": "tool",
            "renderer": "image",
            "asset_dir": self._to_state_path(asset_dir),
            "display_only": True,
            "expires_at": payload.get("expires_at"),
            **image_info,
        }

        with self._locked():
            previous_active = self._active_from_disk()
            self._write_active(active)
            self._delete_asset_dir_for_state(previous_active)

        return self._result(
            "shown",
            operation="show_image",
            content_id=content_id,
            content_type="image",
            message_for_user="已顯示白板圖片。",
            title=active["title"],
            image_basename=image_info["image_basename"],
            width=image_info["width"],
            height=image_info["height"],
        )

    def close(self, content_id: str | None = None) -> dict[str, Any]:
        with self._locked():
            active = self._active_from_disk()
            if not active:
                return self._result(
                    "closed",
                    operation="close",
                    message_for_user="白板已關閉。",
                )
            active_id = active.get("content_id")
            if content_id and content_id != active_id:
                return self._result(
                    "blocked",
                    operation="close",
                    content_id=active_id,
                    content_type=active.get("content_type"),
                    message_for_user="目前白板已經換成新的內容，沒有關閉。",
                    errors=["content_id does not match active whiteboard."],
                )
            try:
                self.active_path.unlink()
            except FileNotFoundError:
                pass
            self._delete_asset_dir_for_state(active)
            return self._result(
                "closed",
                operation="close",
                content_id=active_id,
                content_type=active.get("content_type"),
                message_for_user="白板已關閉。",
            )

    def status(self) -> dict[str, Any]:
        active = self.get_active()
        if not active:
            return self._result(
                "empty",
                operation="status",
                message_for_user="目前沒有開啟白板。",
                active=False,
            )
        return self._result(
            "active",
            operation="status",
            content_id=active.get("content_id"),
            content_type=active.get("content_type"),
            message_for_user="目前有開啟白板。",
            active=True,
            title=active.get("title"),
            created_at=active.get("created_at"),
            updated_at=active.get("updated_at"),
            expires_at=active.get("expires_at"),
            display_only=active.get("display_only", True),
        )

    def get_content(self, content_id: str | None = None, max_chars: int = DEFAULT_GET_CONTENT_CHARS) -> dict[str, Any]:
        active = self.get_active()
        if not active:
            return self._result(
                "empty",
                operation="get_content",
                message_for_user="目前沒有開啟白板。",
                active=False,
            )
        active_id = active.get("content_id")
        content_type = active.get("content_type")
        if content_id and content_id != active_id:
            return self._result(
                "blocked",
                operation="get_content",
                content_id=active_id,
                content_type=content_type,
                message_for_user="目前白板已經換成新的內容。",
                errors=["content_id does not match active whiteboard."],
            )

        if content_type == "markdown":
            path = self.resolve_asset_path(active.get("markdown_path"))
            if path is None:
                return self._result(
                    "blocked",
                    operation="get_content",
                    content_id=active_id,
                    content_type="markdown",
                    message_for_user="白板內容路徑不正確，已拒絕讀取。",
                    errors=["markdown_path is outside the whiteboard assets directory."],
                )
            markdown = ""
            if path and path.exists():
                markdown = path.read_text(encoding="utf-8")
            try:
                limit = int(max_chars)
            except (TypeError, ValueError):
                limit = DEFAULT_GET_CONTENT_CHARS
            limit = max(1, min(limit, 50000))
            truncated = len(markdown) > limit
            if truncated:
                markdown = markdown[:limit]
            return self._result(
                "ok",
                operation="get_content",
                content_id=active_id,
                content_type="markdown",
                message_for_user="已讀取目前白板內容。",
                title=active.get("title"),
                markdown=markdown,
                truncated=truncated,
                max_chars=limit,
            )

        if content_type == "image":
            path = self.resolve_asset_path(active.get("image_path"))
            if path is None:
                return self._result(
                    "blocked",
                    operation="get_content",
                    content_id=active_id,
                    content_type="image",
                    message_for_user="白板圖片路徑不正確，已拒絕讀取。",
                    errors=["image_path is outside the whiteboard assets directory."],
                )
            if not path.is_file():
                return self._result(
                    "blocked",
                    operation="get_content",
                    content_id=active_id,
                    content_type="image",
                    message_for_user="目前白板圖片檔案不存在，已拒絕讀取。",
                    errors=["image_path does not reference an existing file."],
                )
            return self._result(
                "ok",
                operation="get_content",
                content_id=active_id,
                content_type="image",
                message_for_user="已讀取目前白板圖片資訊。",
                title=active.get("title"),
                image_path=str(path),
                image_basename=active.get("image_basename"),
                alt_text=active.get("alt_text"),
                width=active.get("width"),
                height=active.get("height"),
                image_format=active.get("image_format"),
                image_bytes=active.get("image_bytes"),
            )

        return self._result(
            "error",
            operation="get_content",
            content_id=active_id,
            content_type=content_type,
            message_for_user="白板狀態格式不正確。",
            errors=[f"Unsupported content_type: {content_type}"],
        )

    def get_active(self) -> dict[str, Any] | None:
        return self._active_from_disk()

    def active_mtime_ns(self) -> int | None:
        try:
            return self.active_path.stat().st_mtime_ns
        except FileNotFoundError:
            return None
