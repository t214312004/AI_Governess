# ai_voice_assistant/llm/antigravity_cli_client.py
import asyncio
import functools
import json
import os
import re
import shutil
from typing import AsyncGenerator

from .base_client import BaseLLMClient, STREAM_ACTIVITY_KEEPALIVE
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
    re.compile(r"^Error:\s+timed out waiting for response\s*$", re.IGNORECASE),
    re.compile(r"^Error:\s+failed to send message:.*$", re.IGNORECASE | re.DOTALL),
)

_TRAJECTORY_NOT_FOUND_RE = re.compile(r"trajectory not found:", re.IGNORECASE)


def _looks_like_cli_error(text: str) -> bool:
    return any(pattern.match(text.strip()) for pattern in _CLI_ERROR_PATTERNS)


def _looks_like_trajectory_not_found(text: str) -> bool:
    return bool(_TRAJECTORY_NOT_FOUND_RE.search(text))



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
        self.print_timeout = print_timeout or "2m0s"
        self._cancel_flag = False
        self._pty_process = None
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

        try:
            with open(cache_path, "r", encoding="utf-8") as fp:
                cache = json.load(fp)
        except (OSError, json.JSONDecodeError) as exc:
            log_event(
                logger,
                logging.WARNING,
                "antigravity.last_conversations_unreadable",
                path=cache_path,
                error=str(exc),
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

    def _build_command_string(self, text: str, session_id: str | None = None) -> str:
        """組裝 agy 命令字串（pywinpty 需要單一 command string 而非 list）。"""
        agy_path = shutil.which("agy") or "agy"

        def _quote_if_needed(s: str) -> str:
            """只在字串包含空格時才加雙引號。"""
            if " " in s:
                return f'"{s}"'
            return s

        # 對 prompt 文字做 shell escaping — 用雙引號包裹，內部雙引號轉義
        escaped_text = text.replace('"', '\\"')
        parts = [
            _quote_if_needed(agy_path),
            "--dangerously-skip-permissions",
            "--print-timeout",
            self.print_timeout,
            "-p",
            f'"{escaped_text}"',
        ]
        if session_id:
            parts.extend(["--conversation", session_id])
        return " ".join(parts)

    def _extract_incremental_output(self, cleaned: str) -> str:
        """agy resume print mode 會輸出累積 assistant 訊息，只回傳本輪新增部分。"""
        previous = self._last_cleaned_output
        self._last_cleaned_output = cleaned
        if previous and cleaned.startswith(previous):
            return cleaned[len(previous):].lstrip("\r\n")
        return cleaned

    def _run_pty_blocking(self, cmd_str: str) -> tuple[str, int]:
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
            command=cmd_str[:200],
            cwd=self.project_dir,
        )

        proc = PtyProcess.spawn(cmd_str, cwd=self.project_dir)
        self._pty_process = proc

        output_parts = []
        try:
            while proc.isalive():
                if self._cancel_flag:
                    break
                try:
                    line = proc.readline()
                    if line:
                        output_parts.append(line)
                except EOFError:
                    break
                except Exception:
                    break

            # 讀取剩餘輸出
            if not self._cancel_flag:
                try:
                    while True:
                        line = proc.readline()
                        if not line:
                            break
                        output_parts.append(line)
                except (EOFError, Exception):
                    pass
        finally:
            self._pty_process = None

        exit_status = proc.exitstatus if hasattr(proc, 'exitstatus') else -1
        raw_output = "".join(output_parts)
        return raw_output, exit_status

    async def send_message(self, text: str) -> AsyncGenerator[str, None]:
        self._cancel_flag = False
        for attempt in range(2):
            session_id = self._get_resume_session_id()
            cmd_str = self._build_command_string(text, session_id=session_id)
            log_event(
                logger,
                logging.INFO,
                "antigravity.send_message",
                command=cmd_str[:300],
                session_id=session_id,
                attempt=attempt + 1,
            )

            loop = asyncio.get_event_loop()

            # 在背景執行 PTY 進程，同時定期發送 keepalive 給上層
            pty_future = loop.run_in_executor(
                None,
                functools.partial(self._run_pty_blocking, cmd_str),
            )

            # 每 0.8 秒檢查一次是否完成，未完成就發 keepalive
            while not pty_future.done():
                if self._cancel_flag:
                    # 取消時嘗試終止 PTY 進程
                    if self._pty_process is not None:
                        try:
                            self._pty_process.terminate()
                        except Exception:
                            pass
                    pty_future.cancel()
                    return
                yield STREAM_ACTIVITY_KEEPALIVE
                try:
                    await asyncio.wait_for(asyncio.shield(pty_future), timeout=0.8)
                    break  # Future 完成了
                except asyncio.TimeoutError:
                    continue  # 還沒完成，繼續 keepalive
                except asyncio.CancelledError:
                    return

            if self._cancel_flag:
                return

            try:
                raw_output, exit_status = pty_future.result()
            except Exception as e:
                log_event(logger, logging.ERROR, "antigravity.execution_failed", error=str(e))
                yield f"（呼叫 Antigravity 後端發生異常: {e}）"
                return

            log_event(
                logger,
                logging.DEBUG,
                "antigravity.pty_completed",
                exit_status=exit_status,
                raw_output_len=len(raw_output),
            )

            if exit_status not in (None, 0, -1):
                log_event(
                    logger,
                    logging.ERROR,
                    "antigravity.nonzero_exit",
                    exit_status=exit_status,
                    raw_output=raw_output[:500],
                )
                yield f"（agy 執行結束碼 {exit_status}）"
                return

            # 清理 ANSI escape sequences 並提取回覆文字
            cleaned = _strip_ansi(raw_output).strip()

            if _looks_like_cli_error(cleaned):
                log_event(
                    logger,
                    logging.ERROR,
                    "antigravity.cli_error_output",
                    output=cleaned[:500],
                )
                if session_id and attempt == 0 and _looks_like_trajectory_not_found(cleaned):
                    log_event(
                        logger,
                        logging.WARNING,
                        "antigravity.retry_without_stale_session",
                        session_id=session_id,
                    )
                    self.session_id = None
                    self._last_cleaned_output = ""
                    continue
                raise RuntimeError(cleaned)

            if cleaned:
                response = self._extract_incremental_output(cleaned)
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

            # 更新最新的 session_id，以利下一次 --conversation 延續本輪 runtime 對話
            new_id = self._get_latest_conversation_id()
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

    async def cancel(self):
        """取消當前對話請求。"""
        self._cancel_flag = True
        await self.aclose()

    async def aclose(self):
        """釋放資源，終止子進程。"""
        self._cancel_flag = True
        if self._pty_process is not None:
            try:
                self._pty_process.terminate()
            except Exception:
                pass
        self._pty_process = None

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
