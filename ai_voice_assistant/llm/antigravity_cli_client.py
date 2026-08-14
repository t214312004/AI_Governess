# ai_voice_assistant/llm/antigravity_cli_client.py
import asyncio
import functools
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from typing import AsyncGenerator

from .base_client import BaseLLMClient, LLMBackendUnavailableError, STREAM_ACTIVITY_KEEPALIVE
from utils.logger import get_logger, log_event
import logging

logger = get_logger(__name__)

# ANSI escape sequence 清理用正則
_ANSI_ESCAPE_RE = re.compile(
    r"\x1b"          # ESC
    r"(?:"
    r"\[[0-9;?]*[A-Za-z]"   # CSI sequences
    r"|"
    r"\](?:[^\x07\x1b]*)(?:\x07|\x1b\\)" # OSC sequences (ends with BEL or ESC \)
    r"|"
    r"[()][AB012]"           # Character set designation
    r"|"
    r"[>=<]"                 # Keypad mode changes
    r"|"
    r"[78DHM]"               # Other single-char ESC sequences
    r"|"
    r"\][^\x07\x1b]*"        # Catch broken OSC without proper terminator just in case
    r"|"
    r".(?:\r|\n)?"           # Catch any other ESC + 1 char
    r")"
)


def _strip_ansi(text: str) -> str:
    """移除 ANSI/VT escape sequences，並過濾掉 CLI 的警告訊息。"""
    text = _ANSI_ESCAPE_RE.sub("", text)
    # 過濾掉 agy CLI 可能混在 PTY 輸出的 stderr 警告 (如 Warning: ...)
    text = re.sub(r"(?m)^Warning: .*$\r?\n?", "", text)
    return text


_CLI_ERROR_PATTERNS = (
    re.compile(r"^Error:\s+(?:timed out|timeout) waiting for response\s*$", re.IGNORECASE),
    re.compile(r"^Error:\s+failed to send message:.*$", re.IGNORECASE | re.DOTALL),
)

_CLI_ERROR_SUFFIX_PATTERNS = (
    re.compile(r"Error:\s+(?:timed out|timeout) waiting for response\s*$", re.IGNORECASE),
    re.compile(r"Error:\s+failed to send message:.*$", re.IGNORECASE | re.DOTALL),
)

_TRAJECTORY_NOT_FOUND_RE = re.compile(r"trajectory not found:", re.IGNORECASE)

_INTERNAL_OUTPUT_LEAK_PATTERNS = (
    ("thought_tag", re.compile(r"(?im)^<thought\b")),
    (
        "task_status",
        re.compile(r"(?m)^\[\d{4}-\d{2}-\d{2}T[^\]]+\]\s+task-\d+\b"),
    ),
    (
        "runtime_instruction_echo",
        re.compile(r"Runtime instruction for this agy --print call:", re.IGNORECASE),
    ),
    (
        "hidden_reasoning_instruction_echo",
        re.compile(r"Do not include hidden reasoning", re.IGNORECASE),
    ),
)

_PRINT_MODE_RUNTIME_HINT = """Runtime instruction for this agy --print call:
Return only the final user-facing text that should be spoken or shown.
Do not include hidden reasoning, thinking notes, progress messages, tool-use narration, terminal status labels, markdown, emojis, or mode labels such as Underground or Low.
If you need to inspect files, update memory, or use tools, do that silently and then return only the final answer."""

_CONVERSATION_CACHE_READ_ATTEMPTS = 3
_CONVERSATION_CACHE_READ_RETRY_SECONDS = 0.02
_NEW_CONVERSATION_CACHE_WAIT_SECONDS = 1.0
_NEW_CONVERSATION_CACHE_POLL_SECONDS = 0.05
_PTY_READ_POLL_SECONDS = 0.2


def _looks_like_cli_error(text: str) -> bool:
    return any(pattern.match(text.strip()) for pattern in _CLI_ERROR_PATTERNS)


def _extract_cli_error(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    if _looks_like_cli_error(stripped):
        return stripped
    for pattern in _CLI_ERROR_SUFFIX_PATTERNS:
        match = pattern.search(stripped)
        if match:
            return match.group(0).strip()
    return None


def _looks_like_trajectory_not_found(text: str) -> bool:
    return bool(_TRAJECTORY_NOT_FOUND_RE.search(text))


def _detect_internal_output_leak(text: str) -> str | None:
    for reason, pattern in _INTERNAL_OUTPUT_LEAK_PATTERNS:
        if pattern.search(text):
            return reason
    return None



class AntigravityCLIClient(BaseLLMClient):
    """
    Antigravity CLI (agy) client.

    使用 pywinpty (ConPTY) 建立 Windows pseudo-terminal 來執行 agy.exe，
    因為 agy 的 --print 模式在 stdout 被 redirect 時會 hang（TTY 偵測行為）。
    透過 PTY 可以讓 agy 以為自己在寫到真正的 terminal，同時我們從 PTY
    的另一端讀取輸出，不會有黑色視窗閃爍。
    """

    def __init__(
        self,
        project_dir: str = "./agent_workspace",
        session_id: str | None = None,
        print_timeout: str = "",
        **kwargs
    ):
        self.project_dir = os.path.abspath(project_dir)
        os.makedirs(self.project_dir, exist_ok=True)
        self.session_id = session_id
        self.print_timeout = print_timeout or "3m0s"
        self._cancel_flag = False
        self._pty_process = None
        self._send_lock = asyncio.Lock()
        self._state_lock = threading.Lock()
        self._active_request_state = None
        self._last_cleaned_output = ""

    def _get_cli_app_data_dir(self) -> str:
        user_home = os.path.expanduser("~")
        return os.path.join(user_home, ".gemini", "antigravity-cli")

    def _conversation_exists(self, session_id: str | None) -> bool:
        if not session_id:
            return False

        conv_dir = os.path.join(self._get_cli_app_data_dir(), "conversations")
        if not os.path.exists(conv_dir):
            log_event(logger, logging.DEBUG, "antigravity.cli_conv_dir_not_found", path=conv_dir)
            return False

        for extension in (".pb", ".db"):
            if os.path.exists(os.path.join(conv_dir, f"{session_id}{extension}")):
                return True
        return False

    def _get_latest_conversation_id(self) -> str | None:
        """讀取 agy CLI 針對目前 project_dir 記錄的最新 conversation id。"""
        cache_path = os.path.join(
            self._get_cli_app_data_dir(),
            "cache",
            "last_conversations.json",
        )
        if not os.path.exists(cache_path):
            log_event(logger, logging.DEBUG, "antigravity.last_conversations_not_found", path=cache_path)
            return None

        cache = None
        last_error = None
        for attempt in range(_CONVERSATION_CACHE_READ_ATTEMPTS):
            try:
                with open(cache_path, "r", encoding="utf-8") as fp:
                    cache = json.load(fp)
                last_error = None
                break
            except (OSError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt + 1 < _CONVERSATION_CACHE_READ_ATTEMPTS:
                    time.sleep(_CONVERSATION_CACHE_READ_RETRY_SECONDS)

        if last_error is not None:
            log_event(
                logger,
                logging.WARNING,
                "antigravity.last_conversations_unreadable",
                path=cache_path,
                error=str(last_error),
            )
            return None

        if not isinstance(cache, dict):
            log_event(logger, logging.WARNING, "antigravity.last_conversations_invalid", path=cache_path)
            return None

        target_dir = os.path.normcase(os.path.abspath(self.project_dir))
        for path, conv_id in cache.items():
            if not isinstance(path, str) or not isinstance(conv_id, str):
                continue
            if os.path.normcase(os.path.abspath(path)) != target_dir:
                continue
            if self._conversation_exists(conv_id):
                log_event(
                    logger,
                    logging.DEBUG,
                    "antigravity.detected_cached_conv",
                    conv_id=conv_id,
                    project_dir=self.project_dir,
                )
                return conv_id
            log_event(
                logger,
                logging.WARNING,
                "antigravity.cached_conv_missing",
                conv_id=conv_id,
                project_dir=self.project_dir,
            )
            return None

        log_event(
            logger,
            logging.DEBUG,
            "antigravity.cached_conv_not_found_for_project",
            project_dir=self.project_dir,
        )
        return None

    async def _wait_for_new_conversation_id(
        self,
        previous_conversation_id: str | None,
    ) -> str | None:
        """等待 agy 寫入新 conversation id，且不接受啟動前的舊 id。"""
        deadline = time.monotonic() + _NEW_CONVERSATION_CACHE_WAIT_SECONDS
        while True:
            conversation_id = self._get_latest_conversation_id()
            if conversation_id and conversation_id != previous_conversation_id:
                return conversation_id
            if time.monotonic() >= deadline:
                log_event(
                    logger,
                    logging.WARNING,
                    "antigravity.new_conversation_not_detected",
                    previous_conversation_id=previous_conversation_id,
                    project_dir=self.project_dir,
                )
                return None
            await asyncio.sleep(_NEW_CONVERSATION_CACHE_POLL_SECONDS)

    def _get_resume_session_id(self) -> str | None:
        if not self.session_id:
            return None
        if self._conversation_exists(self.session_id):
            return self.session_id

        log_event(
            logger,
            logging.WARNING,
            "antigravity.session_id_stale",
            session_id=self.session_id,
        )
        self.session_id = None
        self._last_cleaned_output = ""
        return None

    def _build_command_args(
        self,
        text: str,
        session_id: str | None = None,
    ) -> list[str]:
        """組裝 agy argv；直接傳 list 給 pywinpty，避免 prompt 被重新切割。"""
        agy_path = shutil.which("agy") or "agy"

        prompt_text = f"{_PRINT_MODE_RUNTIME_HINT}\n\nUser message:\n{text}"
        parts = [
            agy_path,
        ]
        parts.extend(
            [
                "--add-dir",
                self.project_dir,
                "--dangerously-skip-permissions",
                "--print-timeout",
                self.print_timeout,
                "-p",
                prompt_text,
            ]
        )
        if session_id:
            parts.extend(["--conversation", session_id])
        return parts

    @staticmethod
    def _format_command_for_log(command: list[str] | tuple[str, ...] | str) -> str:
        """只供 log 顯示；process 啟動使用原始 argv。"""
        if isinstance(command, str):
            return command
        return subprocess.list2cmdline(list(command))

    def _extract_incremental_output(self, cleaned: str) -> str:
        """agy resume print mode 會輸出累積 assistant 訊息，只回傳本輪新增部分。"""
        previous = self._last_cleaned_output
        self._last_cleaned_output = cleaned
        if previous and len(cleaned) > len(previous) and cleaned.startswith(previous):
            return cleaned[len(previous):].lstrip("\r\n")
        return cleaned

    def _run_pty_blocking(
        self,
        command: list[str] | tuple[str, ...] | str,
        request_state=None,
    ) -> tuple[str, int | None]:
        """
        在 blocking 模式下透過 pywinpty 執行 agy 並收集全部輸出。
        此方法設計為在 executor thread 中呼叫，不會阻塞 event loop。

        Returns:
            (collected_output, exit_status)
        """
        from winpty import PtyProcess

        log_event(
            logger,
            logging.DEBUG,
            "antigravity.pty_spawning",
            command=self._format_command_for_log(command)[:200],
            cwd=self.project_dir,
        )

        proc = PtyProcess.spawn(command, cwd=self.project_dir)
        terminate_after_spawn = False
        with self._state_lock:
            if request_state is None:
                terminate_after_spawn = self._cancel_flag
            else:
                terminate_after_spawn = (
                    self._active_request_state is not request_state
                    or request_state["cancel_event"].is_set()
                )
            if not terminate_after_spawn:
                self._pty_process = proc
                if request_state is not None:
                    request_state["process"] = proc

        if terminate_after_spawn:
            try:
                proc.terminate()
            except Exception:
                pass

        def is_cancelled() -> bool:
            if request_state is None:
                return self._cancel_flag
            return request_state["cancel_event"].is_set()

        output_parts = []
        read_error = None
        fileobj = getattr(proc, "fileobj", None)
        use_timed_read = (
            fileobj is not None
            and callable(getattr(fileobj, "settimeout", None))
            and callable(getattr(proc, "read", None))
        )
        if use_timed_read:
            fileobj.settimeout(_PTY_READ_POLL_SECONDS)
        try:
            while True:
                if is_cancelled():
                    break
                try:
                    chunk = proc.read(4096) if use_timed_read else proc.readline()
                    if not chunk:
                        break
                    output_parts.append(chunk)
                except socket.timeout:
                    if not proc.isalive():
                        break
                    continue
                except EOFError:
                    break
                except Exception as exc:
                    read_error = exc
                    break
        finally:
            if is_cancelled() or read_error is not None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            close_process = getattr(proc, "close", None)
            if callable(close_process):
                try:
                    close_process()
                except Exception as exc:
                    if read_error is None and not is_cancelled():
                        read_error = exc
            with self._state_lock:
                if self._pty_process is proc:
                    self._pty_process = None
                if request_state is not None and request_state.get("process") is proc:
                    request_state["process"] = None

        if read_error is not None:
            raise RuntimeError("Antigravity CLI PTY output read failed.") from read_error

        exit_status = proc.exitstatus if hasattr(proc, 'exitstatus') else -1
        raw_output = "".join(output_parts)
        return raw_output, exit_status

    async def send_message(self, text: str) -> AsyncGenerator[str, None]:
        async with self._send_lock:
            request_state = {
                "cancel_event": threading.Event(),
                "process": None,
            }
            with self._state_lock:
                self._cancel_flag = False
                self._active_request_state = request_state
            try:
                async for chunk in self._send_message_locked(text, request_state):
                    yield chunk
            finally:
                request_state["cancel_event"].set()
                process = request_state.get("process")
                if process is not None:
                    try:
                        process.terminate()
                    except Exception:
                        pass
                with self._state_lock:
                    if self._active_request_state is request_state:
                        self._active_request_state = None
                    if self._pty_process is process:
                        self._pty_process = None

    async def _send_message_locked(self, text: str, request_state) -> AsyncGenerator[str, None]:
        for attempt in range(2):
            session_id = self._get_resume_session_id()
            previous_conversation_id = (
                None if session_id else self._get_latest_conversation_id()
            )
            command = self._build_command_args(
                text,
                session_id=session_id,
            )
            command_for_log = self._format_command_for_log(command)
            log_event(
                logger,
                logging.INFO,
                "antigravity.send_message",
                command=command_for_log[:300],
                session_id=session_id,
                attempt=attempt + 1,
            )

            loop = asyncio.get_event_loop()

            # 在背景執行 PTY 進程，同時定期發送 keepalive 給上層
            pty_future = loop.run_in_executor(
                None,
                functools.partial(self._run_pty_blocking, command, request_state),
            )

            # 每 0.8 秒檢查一次是否完成，未完成就發 keepalive
            while not pty_future.done():
                if request_state["cancel_event"].is_set():
                    # 取消時嘗試終止 PTY 進程
                    process = request_state.get("process")
                    if process is not None:
                        try:
                            process.terminate()
                        except Exception:
                            pass
                    try:
                        await asyncio.wait_for(asyncio.shield(pty_future), timeout=2.0)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        pass
                    except Exception:
                        pass
                    return
                yield STREAM_ACTIVITY_KEEPALIVE
                try:
                    await asyncio.wait_for(asyncio.shield(pty_future), timeout=0.8)
                    break  # Future 完成了
                except asyncio.TimeoutError:
                    continue  # 還沒完成，繼續 keepalive
                except asyncio.CancelledError:
                    return

            if request_state["cancel_event"].is_set():
                return

            try:
                raw_output, exit_status = pty_future.result()
            except Exception as e:
                log_event(logger, logging.ERROR, "antigravity.execution_failed", error=str(e))
                raise LLMBackendUnavailableError(
                    "Antigravity CLI backend 執行失敗。"
                ) from e

            log_event(
                logger,
                logging.DEBUG,
                "antigravity.pty_completed",
                exit_status=exit_status,
                raw_output_len=len(raw_output),
            )

            # 清理 ANSI escape sequences 並提取回覆文字
            cleaned = _strip_ansi(raw_output).strip()

            cli_error = _extract_cli_error(cleaned)
            if cli_error:
                log_event(
                    logger,
                    logging.ERROR,
                    "antigravity.cli_error_output",
                    output_chars=len(cli_error),
                    error_output=cli_error[:500],
                )
                if session_id and attempt == 0 and _looks_like_trajectory_not_found(cli_error):
                    log_event(
                        logger,
                        logging.WARNING,
                        "antigravity.retry_without_stale_session",
                        session_id=session_id,
                    )
                    self.session_id = None
                    self._last_cleaned_output = ""
                    continue
                if exit_status not in (None, 0, -1):
                    raise LLMBackendUnavailableError(cli_error)
                raise RuntimeError(cli_error)

            if exit_status not in (None, 0, -1):
                log_event(
                    logger,
                    logging.ERROR,
                    "antigravity.nonzero_exit",
                    exit_status=exit_status,
                    output_chars=len(raw_output),
                    output_snippet=(cleaned[:500] if cleaned else raw_output[:500]),
                )
                raise LLMBackendUnavailableError(
                    f"Antigravity CLI exited with code {exit_status}."
                )

            internal_leak_reason = _detect_internal_output_leak(cleaned)
            if internal_leak_reason:
                log_event(
                    logger,
                    logging.ERROR,
                    "antigravity.internal_output_leak",
                    reason=internal_leak_reason,
                    cleaned_len=len(cleaned),
                )
                self.session_id = None
                self._last_cleaned_output = ""
                raise RuntimeError(
                    f"Antigravity CLI returned internal output: {internal_leak_reason}"
                )

            if cleaned:
                if session_id:
                    response = self._extract_incremental_output(cleaned)
                else:
                    self._last_cleaned_output = cleaned
                    response = cleaned
                if response:
                    yield response
                else:
                    log_event(
                        logger,
                        logging.WARNING,
                        "antigravity.empty_incremental_response",
                        cleaned_len=len(cleaned),
                    )
            else:
                log_event(
                    logger,
                    logging.WARNING,
                    "antigravity.empty_response_after_strip",
                    raw_output_len=len(raw_output),
                    raw_output_head=repr(raw_output[:200]),
                )

            # Resume 成功時沿用已知 id；新 conversation 只接受啟動後變更的 cache id。
            new_id = session_id or await self._wait_for_new_conversation_id(
                previous_conversation_id
            )
            if new_id:
                if self.session_id != new_id:
                    log_event(
                        logger,
                        logging.INFO,
                        "antigravity.session_id_updated",
                        old=self.session_id,
                        new=new_id,
                    )
                    self.session_id = new_id
            return

    def request_cancel(self):
        """Synchronously mark the currently active request for cancellation."""
        self._cancel_flag = True
        with self._state_lock:
            request_state = self._active_request_state
            if request_state is not None:
                request_state["cancel_event"].set()
                process = request_state.get("process")
            else:
                process = self._pty_process
        if process is not None:
            try:
                process.terminate()
            except Exception:
                pass
        with self._state_lock:
            if self._pty_process is process:
                self._pty_process = None

    async def cancel(self):
        """取消當前對話請求。"""
        self.request_cancel()

    async def aclose(self):
        """釋放資源，終止子進程。"""
        self.request_cancel()

    async def refresh_session(self) -> bool:
        """刷新 Session，清空當前對話會話，以便下次自動建立新對話。"""
        self.session_id = None
        self._last_cleaned_output = ""
        log_event(logger, logging.INFO, "antigravity.session_refreshed")
        return True

    async def ensure_ready(self) -> bool:
        """確認 agy 執行檔可用。"""
        agy_path = shutil.which("agy")
        if not agy_path:
            raise RuntimeError("本機環境找不到 agy 執行檔，請確認已正確安裝並加入 PATH。")
        # 驗證 pywinpty 可用
        try:
            from winpty import PtyProcess  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "pywinpty 未安裝，請執行 pip install pywinpty 來安裝。"
            )
        log_event(logger, logging.INFO, "antigravity.ready", path=agy_path)
        return True
