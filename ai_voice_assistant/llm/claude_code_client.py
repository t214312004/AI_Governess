import asyncio
import inspect
import json
import os
import shutil
import sys
from typing import AsyncGenerator

from .base_client import BaseLLMClient, STREAM_ACTIVITY_KEEPALIVE


class ClaudeCodeClient(BaseLLMClient):
    """Launch Claude Code CLI as a subprocess and expose the shared stream interface."""

    def __init__(
        self,
        model: str = "sonnet",
        max_turns: int = 3,
        project_dir: str = "./agent_workspace",
        permission_mode: str = "bypassPermissions",
        allowed_tools: str = "",
        tools: str = "default",
        session_id: str | None = None,
    ):
        self.model = model
        self.max_turns = max_turns
        self.project_dir = os.path.abspath(project_dir)
        os.makedirs(self.project_dir, exist_ok=True)
        self.permission_mode = permission_mode
        self.allowed_tools = allowed_tools
        self.tools = tools
        self.session_id = session_id
        self.process = None
        self._cancel_flag = False
        self._stderr_lines = []

    def _build_command(self, text: str) -> list[str]:
        claude_path = shutil.which("claude") or "claude"
        cmd = [
            claude_path,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--model",
            self.model,
            "--max-turns",
            str(self.max_turns),
        ]
        if self.permission_mode:
            cmd.extend(["--permission-mode", self.permission_mode])
        if self.allowed_tools:
            cmd.extend(["--allowedTools", self.allowed_tools])
        if self.tools:
            cmd.extend(["--tools", self.tools])
        if self.session_id:
            cmd.extend(["--resume", self.session_id])
        cmd.append(text)
        return cmd

    def _extract_text_delta(self, data: dict) -> str:
        if data.get("type") == "content_block_delta":
            delta = data.get("delta", {})
            if delta.get("type") == "text_delta":
                return delta.get("text", "")

        if data.get("type") == "stream_event":
            event = data.get("event", {})
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    return delta.get("text", "")
        return ""

    @staticmethod
    def _is_activity_event(data: dict) -> bool:
        msg_type = data.get("type")
        if msg_type == "system" and data.get("subtype") in {
            "api_retry",
            "init",
            "plugin_install",
        }:
            return True

        if msg_type != "stream_event":
            return False

        event = data.get("event", {})
        event_type = event.get("type")
        if event_type in {"message_start", "message_delta"}:
            return True
        if event_type == "content_block_start":
            block = event.get("content_block", {})
            return block.get("type") != "text"
        if event_type in {"content_block_stop", "tool_use", "tool_result"}:
            return True
        return False

    def _remember_session_id(self, data: dict) -> None:
        session_id = data.get("session_id")
        if not session_id and isinstance(data.get("event"), dict):
            session_id = data["event"].get("session_id")
        if session_id:
            self.session_id = session_id

    async def _read_stderr(self):
        try:
            while self.process and self.process.stderr:
                line = await self.process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    self._stderr_lines.append(text)
                    self._stderr_lines = self._stderr_lines[-20:]
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def send_message(self, text: str) -> AsyncGenerator[str, None]:
        self._cancel_flag = False
        self._stderr_lines = []
        cmd = self._build_command(text)
        stderr_task = None

        try:
            # Hide the external CLI window on Windows.
            creationflags = 0
            if sys.platform == "win32":
                import subprocess

                creationflags = subprocess.CREATE_NO_WINDOW

            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.project_dir,
                creationflags=creationflags,
            )
            stderr_task = asyncio.create_task(self._read_stderr())

            async for line in self.process.stdout:
                if self._cancel_flag:
                    break
                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue

                try:
                    data = json.loads(line_str)
                    self._remember_session_id(data)
                    chunk = self._extract_text_delta(data)
                    if chunk:
                        yield chunk
                    elif self._is_activity_event(data):
                        yield STREAM_ACTIVITY_KEEPALIVE
                except json.JSONDecodeError:
                    continue

            if self.process:
                await self._wait_for_process_exit()
                if (
                    not self._cancel_flag
                    and self.process.returncode not in (None, 0)
                ):
                    stderr_tail = "\n".join(self._stderr_lines[-5:])
                    raise RuntimeError(
                        f"Claude Code CLI 結束碼 {self.process.returncode}: {stderr_tail}"
                    )
        finally:
            if stderr_task and not stderr_task.done():
                stderr_task.cancel()
                try:
                    await stderr_task
                except asyncio.CancelledError:
                    pass
            if self.process and self.process.returncode is None:
                try:
                    self.process.kill()
                except ProcessLookupError:
                    pass
                await self._wait_for_process_exit()

    async def cancel(self):
        self._cancel_flag = True
        await self.aclose()

    async def _wait_for_process_exit(self):
        if not self.process:
            return
        wait_result = self.process.wait()
        if inspect.isawaitable(wait_result):
            await wait_result

    async def aclose(self):
        if self.process and self.process.returncode is None:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass  # pragma: no cover
            await self._wait_for_process_exit()
        self.process = None

    async def refresh_session(self) -> bool:
        # Claude Code `-p` has no ACP-style session/new, so clear the id.
        self.session_id = None
        return True
