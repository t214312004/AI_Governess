# ai_voice_assistant/llm/antigravity_cli_client.py
import asyncio
import functools
import os
import re
import shutil
import glob
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

    def _get_latest_conversation_id(self) -> str | None:
        """掃描本機 antigravity conversations 目錄，找出最新變動的 conversation UUID"""
        user_home = os.path.expanduser("~")
        conv_dir = os.path.join(user_home, ".gemini", "antigravity", "conversations")
        if not os.path.exists(conv_dir):
            log_event(logger, logging.DEBUG, "antigravity.conv_dir_not_found", path=conv_dir)
            return None

        # 尋找所有的 db 或 pb 檔案
        files = glob.glob(os.path.join(conv_dir, "*"))
        # 過濾掉 shm 與 wal 暫存檔，只留下主對話檔案
        valid_files = [f for f in files if f.endswith(('.db', '.pb'))]
        if not valid_files:
            return None

        latest_file = max(valid_files, key=os.path.getmtime)
        base_name = os.path.basename(latest_file)
        conv_id = os.path.splitext(base_name)[0]
        log_event(logger, logging.DEBUG, "antigravity.detected_latest_conv", conv_id=conv_id, file=base_name)
        return conv_id

    def _build_command_string(self, text: str) -> str:
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
            "--add-dir",
            _quote_if_needed(self.project_dir),
            "-p",
            f'"{escaped_text}"',
        ]
        # 取得要延續的 session_id（優先使用當前 session_id，否則抓取最新的）
        session_id = self.session_id or self._get_latest_conversation_id()
        
        if session_id:
            parts.extend(["--conversation", session_id])
        # 如果是全新的環境（完全沒有任何歷史對話），就不帶 --conversation 參數，agy 會自動建立新的。
        return " ".join(parts)


    def _run_pty_blocking(self, cmd_str: str) -> tuple[str, int]:
        """
        在 blocking 模式下透過 pywinpty 執行 agy 並收集全部輸出。
        此方法設計為在 executor thread 中呼叫，不會阻塞 event loop。

        Returns:
            (collected_output, exit_status)
        """
        from winpty import PtyProcess

        log_event(logger, logging.DEBUG, "antigravity.pty_spawning", command=cmd_str[:200])

        proc = PtyProcess.spawn(cmd_str)
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
        cmd_str = self._build_command_string(text)
        log_event(
            logger,
            logging.INFO,
            "antigravity.send_message",
            command=cmd_str[:300],
            session_id=self.session_id,
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

        if cleaned:
            yield cleaned
        else:
            log_event(
                logger,
                logging.WARNING,
                "antigravity.empty_response_after_strip",
                raw_output_len=len(raw_output),
                raw_output_head=repr(raw_output[:200]),
            )

        # 更新最新的 session_id，以利下一次 --conversation 延續對話
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
