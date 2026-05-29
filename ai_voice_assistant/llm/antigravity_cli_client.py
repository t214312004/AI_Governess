# ai_voice_assistant/llm/antigravity_cli_client.py
import asyncio
import inspect
import logging
import os
import shutil
import sys
import json
import sqlite3
import re
from typing import AsyncGenerator

from .base_client import BaseLLMClient, STREAM_ACTIVITY_KEEPALIVE
from utils.logger import get_logger, log_event

logger = get_logger(__name__)


class AntigravityCLIClient(BaseLLMClient):
    """
    Antigravity CLI (language_server agentapi) client.
    Bypasses TTY limits and stdout redirection blocks by executing via agentapi 
    and reading direct SQLite database payloads asynchronously.
    """

    def __init__(
        self,
        project_dir: str = "./agent_workspace",
        print_timeout: str = "",
    ):
        self.project_dir = os.path.abspath(project_dir)
        os.makedirs(self.project_dir, exist_ok=True)
        self.session_id: str | None = None
        self.process = None
        self._cancel_flag = False

        # 自動尋找 language_server.exe 實體路徑
        local_appdata = os.environ.get("LOCALAPPDATA", r"C:\Users\t2143\AppData\Local")
        self.ls_path = os.path.join(
            local_appdata, 
            "Programs", 
            "antigravity", 
            "resources", 
            "bin", 
            "language_server.exe"
        )
        if not os.path.exists(self.ls_path):
            # 備用路徑
            self.ls_path = r"C:\Users\t2143\AppData\Local\Programs\antigravity\resources\bin\language_server.exe"

    @staticmethod
    def _extract_ai_response(payload_bytes: bytes) -> str | None:
        """從二進位 protobuf step_payload 中，以啟發式 Strings 提取法安全擷取 AI 回覆字串。"""
        try:
            text = payload_bytes.decode('utf-8', errors='ignore')
            
            # [\x20-\x7e] 涵蓋所有 ASCII 可列印字元 (英數、符號)
            # [\u4e00-\u9fff] 涵蓋中文
            # [\u3000-\u303f\uff00-\uffef] 涵蓋中文全形標點符號
            candidates = []
            matches = re.findall(r'[\x20-\x7e\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\s]{15,}', text)
            for m in matches:
                m_strip = m.strip()
                # 排除明顯為系統或配置的字串
                if (
                    "protobuf" not in m_strip 
                    and "com.google" not in m_strip 
                    and "Cascade" not in m_strip 
                    and "workspaceUris" not in m_strip
                ):
                    candidates.append(m_strip)
            if candidates:
                candidates.sort(key=len, reverse=True)
                content = candidates[0]
                # 清洗開頭與尾隨的 bot 特徵碼
                cleaned = re.sub(r'^\s*\d*\(?bot-[a-zA-Z0-9\-]+\)?\s*', '', content).strip()
                cleaned = re.sub(r'\s*\d*\(?bot-[a-zA-Z0-9\-]+\)?\s*$', '', cleaned).strip()
                return cleaned
        except Exception as e:
            logger.error(f"解析 SQLite 步驟 payload 異常: {e}", exc_info=True)
        return None

    def _build_subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["USERPROFILE"] = r"C:\Users\t2143"
        env["HOMEPATH"] = r"\Users\t2143"
        env["HOMEDRIVE"] = "C:"
        env["LOCALAPPDATA"] = r"C:\Users\t2143\AppData\Local"
        env["APPDATA"] = r"C:\Users\t2143\AppData\Roaming"
        return env

    async def send_message(self, text: str) -> AsyncGenerator[str, None]:
        self._cancel_flag = False
        
        # 加上強烈的語音助手 Prompt 指示，徹底避免 Agent 在語音對答中去呼叫 Tool
        wrapped_prompt = (
            "【請注意：這是一個語音助手對話，請絕對不要調用任何 Tool 或是執行指令，"
            "請直接以繁體中文對我的話進行簡短精確的文字回覆。】\n"
            f"使用者說：{text}"
        )

        if self.session_id:
            cmd = [
                self.ls_path,
                "agentapi",
                "send-message",
                self.session_id,
                wrapped_prompt
            ]
            log_event(logger, logging.INFO, "antigravity.send_message.continue", session_id=self.session_id)
        else:
            cmd = [
                self.ls_path,
                "agentapi",
                "new-conversation",
                wrapped_prompt
            ]
            log_event(logger, logging.INFO, "antigravity.send_message.new")

        # 1. 啟動背景隱藏 API 進程
        try:
            creationflags = 0
            if sys.platform == "win32":
                import subprocess
                creationflags = subprocess.CREATE_NO_WINDOW

            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=self.project_dir,
                env=self._build_subprocess_env(),
                creationflags=creationflags
            )

            # 2. 異步等待進程結束，並且在等待期間發送心跳以防上層 UI 判定卡死
            stdout_bytes = b""
            while self.process.returncode is None:
                if self._cancel_flag:
                    try:
                        self.process.terminate()
                    except Exception:
                        pass
                    return

                try:
                    # 異步非阻塞等待
                    chunk = await asyncio.wait_for(self.process.stdout.read(1024), timeout=0.8)
                    if chunk:
                        stdout_bytes += chunk
                except asyncio.TimeoutError:
                    yield STREAM_ACTIVITY_KEEPALIVE

            # 補讀取剩餘的所有資料
            remaining = await self.process.stdout.read()
            if remaining:
                stdout_bytes += remaining

            # 3. 解析 API 輸出的對話 Metadata 以更新/獲取 session_id
            decoded_out = ""
            for enc in ["utf-16", "utf-8", "utf-8-sig"]:
                try:
                    decoded_out = stdout_bytes.decode(enc).strip()
                    if "conversationMetadata" in decoded_out:
                        break
                except Exception:
                    pass
            if not decoded_out:
                decoded_out = stdout_bytes.decode("utf-8", errors="replace").strip()

            conv_id = None
            try:
                metadata = json.loads(decoded_out)
                conv_id = metadata["response"]["conversationMetadata"]["metadata"]["sourceMetadata"]["tool"]["conversationId"]
            except Exception:
                # Fallback 使用正則提取 UUID 格式
                uuid_match = re.search(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', decoded_out)
                if uuid_match:
                    conv_id = uuid_match.group(0)

            if conv_id:
                if self.session_id != conv_id:
                    log_event(logger, logging.INFO, "antigravity.session_id_updated", old=self.session_id, new=conv_id)
                    self.session_id = conv_id
            else:
                log_event(logger, logging.ERROR, "antigravity.parse_metadata_failed", output=decoded_out[:1000])
                raise RuntimeError("無法解析對話 Metadata 或是取得對話 ID")

            # 4. 輪詢讀取本地 SQLite 資料庫獲取最新對話回覆
            user_home = os.path.expanduser("~")
            db_path = os.path.join(user_home, ".gemini", "antigravity", "conversations", f"{self.session_id}.db")

            if not os.path.exists(db_path):
                raise FileNotFoundError(f"找不到本地對話資料庫: {db_path}")

            ai_reply = None
            # 最多輪詢等待 15 秒以防非同步資料落盤延遲
            for _ in range(30):
                if self._cancel_flag:
                    return
                await asyncio.sleep(0.5)
                try:
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT step_payload FROM steps WHERE step_type = 15 ORDER BY idx DESC LIMIT 1;")
                    row = cursor.fetchone()
                    conn.close()
                    
                    if row and row[0]:
                        extracted = self._extract_ai_response(row[0])
                        if extracted:
                            ai_reply = extracted
                            break
                except Exception:
                    pass

            if ai_reply:
                # 為了更好的 TTS 與發音合成，我們直接 Yield 完整的乾淨回覆文字
                yield ai_reply
            else:
                log_event(logger, logging.WARNING, "antigravity.response_not_found", session_id=self.session_id)
                yield "（抱歉，助理未能及時將答覆寫入本地數據庫，請再試一次。）"

        except Exception as e:
            log_event(logger, logging.ERROR, "antigravity.execution_failed", error=str(e))
            yield f"（呼叫 Antigravity 後端發生異常: {e}）"
        finally:
            self.process = None

    async def cancel(self):
        """取消當前對話請求。"""
        self._cancel_flag = True
        await self.aclose()

    async def aclose(self):
        """釋放資源，終止子進程。"""
        self._cancel_flag = True
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
            except Exception:
                pass
        self.process = None

    async def refresh_session(self) -> bool:
        """刷新 Session，清空當前對話會話，以便下次自動建立新對話。"""
        self.session_id = None
        log_event(logger, logging.INFO, "antigravity.session_refreshed")
        return True

    async def ensure_ready(self) -> bool:
        """確認官方語言伺服器執行檔存在且可用。"""
        if not os.path.exists(self.ls_path):
            raise RuntimeError(
                f"Antigravity 語言伺服器未安裝，或路徑不正確：{self.ls_path}。\n"
                "請先確認本機是否已安裝官方 IDE 插件環境。"
            )
        log_event(logger, logging.INFO, "antigravity.ready", path=self.ls_path)
        return True
