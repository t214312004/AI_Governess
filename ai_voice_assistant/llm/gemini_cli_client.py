import json
import shutil
import asyncio
import os
import sys
import logging
from typing import AsyncGenerator
from .base_client import BaseLLMClient, STREAM_ACTIVITY_KEEPALIVE
from utils.logger import get_logger, log_event

logger = get_logger(__name__)

class GeminiCLIClient(BaseLLMClient):
    """
    Communicate through Gemini CLI ACP mode to reduce startup latency.
    """
    def __init__(self, project_dir: str = "./", session_id: str = None):
        self.project_dir = os.path.abspath(project_dir)
        os.makedirs(self.project_dir, exist_ok=True)
        self.session_id = session_id
        self.process = None
        self._request_id = 1
        self._receive_task = None
        self._ready_event = asyncio.Event()
        self._response_futures = {}
        self._buffered_responses = {}
        self._streaming_queues = {}
        self._cancel_flag = False
        self._active_prompt_req_id = None
        self._start_lock = None
        self._stderr_task = None

    @staticmethod
    def _enqueue_stream_chunk(queue: asyncio.Queue, chunk_text: str):
        if chunk_text == STREAM_ACTIVITY_KEEPALIVE:
            queue.put_nowait(chunk_text)
            return

        normalized_chunk = GeminiCLIClient._normalize_stream_chunk(queue, chunk_text)
        if not normalized_chunk:
            return

        queue.put_nowait(normalized_chunk)

    @staticmethod
    def _mark_stream_replay_boundary(queue: asyncio.Queue):
        if getattr(queue, "emitted_text", ""):
            queue.replay_cursor = 0

    @staticmethod
    def _normalize_stream_chunk(queue: asyncio.Queue, chunk_text: str) -> str | None:
        last_chunk = getattr(queue, "last_chunk", None)
        if chunk_text == last_chunk:
            log_event(
                logger,
                logging.DEBUG,
                "acp.chunk_skipped",
                reason="duplicate",
                text=chunk_text[:50] + "...",
            )
            return None

        queue.last_chunk = chunk_text
        emitted_text = getattr(queue, "emitted_text", "")
        replay_cursor = getattr(queue, "replay_cursor", None)

        if emitted_text and replay_cursor is not None:
            existing_slice = emitted_text[replay_cursor : replay_cursor + len(chunk_text)]
            if existing_slice == chunk_text:
                queue.replay_cursor = replay_cursor + len(chunk_text)
                log_event(
                    logger,
                    logging.DEBUG,
                    "acp.chunk_skipped",
                    reason="replayed_prefix",
                    text=chunk_text[:50] + "...",
                )
                return None

            remaining_text = emitted_text[replay_cursor:]
            if remaining_text and chunk_text.startswith(remaining_text):
                suffix = chunk_text[len(remaining_text):]
                queue.replay_cursor = len(emitted_text)
                if suffix:
                    queue.emitted_text = emitted_text + suffix
                    return suffix
                log_event(
                    logger,
                    logging.DEBUG,
                    "acp.chunk_skipped",
                    reason="replayed_prefix",
                    text=chunk_text[:50] + "...",
                )
                return None

            queue.replay_cursor = None

        queue.emitted_text = emitted_text + chunk_text
        return chunk_text

    def _persist_session_id(self):
        # Session IDs are runtime-only state and should not be persisted to config.
        return

    async def _drain_task(self, task, *, task_name: str, timeout: float = 1.0):
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except asyncio.CancelledError:
            pass  # pragma: no cover
        except asyncio.TimeoutError:
            log_event(
                logger,
                logging.WARNING,
                "acp.shutdown_task_timeout",
                task=task_name,
                timeout_seconds=timeout,
            )
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "acp.shutdown_task_failed",
                task=task_name,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    async def _wait_for_process_exit(self, process, *, timeout: float = 3.0):
        if process is None:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            log_event(
                logger,
                logging.WARNING,
                "acp.process_wait_timeout",
                timeout_seconds=timeout,
            )
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "acp.process_wait_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )

    async def _terminate_process(self, process):
        if process is None or process.returncode is not None:
            return

        stdin = getattr(process, "stdin", None)
        if stdin is not None:
            try:
                stdin.close()
            except Exception:
                pass
            wait_closed = getattr(stdin, "wait_closed", None)
            if callable(wait_closed):
                try:
                    await asyncio.wait_for(wait_closed(), timeout=1.0)
                except Exception:
                    pass

        if process.returncode is not None:
            return

        pid = getattr(process, "pid", None)
        if sys.platform == "win32" and isinstance(pid, int) and pid > 0:
            import subprocess

            creationflags = subprocess.CREATE_NO_WINDOW
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/T",
                    "/F",
                    "/PID",
                    str(pid),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                await asyncio.wait_for(killer.wait(), timeout=5.0)
            except Exception:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass  # pragma: no cover
        else:
            try:
                process.kill()
            except ProcessLookupError:
                pass  # pragma: no cover

        await self._wait_for_process_exit(process)

    async def _cleanup_failed_start(self):
        await self._drain_task(self._receive_task, task_name="receive")
        await self._drain_task(self._stderr_task, task_name="stderr")

        process = self.process
        self.process = None
        self._receive_task = None
        self._stderr_task = None
        self._active_prompt_req_id = None
        self.session_id = None
        self._persist_session_id()

        for future in list(self._response_futures.values()):
            if not future.done():
                future.cancel()
        self._response_futures.clear()
        self._buffered_responses.clear()
        self._streaming_queues.clear()

        if process and process.returncode is None:
            await self._terminate_process(process)

    async def _start_acp(self):
        if self._start_lock is None:
            self._start_lock = asyncio.Lock()

        async with self._start_lock:
            # Keep startup checks and subprocess creation atomic.
            if self.process and self.process.returncode is None:
                log_event(logger, logging.DEBUG, "acp.start_skipped", reason="already_running")
                return

            gemini_path = shutil.which("gemini") or "gemini"
            cmd = [gemini_path, "--acp", "--yolo"]
            startup_succeeded = False

            creationflags = 0
            if sys.platform == "win32":
                import subprocess
                creationflags = subprocess.CREATE_NO_WINDOW

            try:
                log_event(
                    logger,
                    logging.DEBUG,
                    "acp.starting",
                    command=" ".join(cmd),
                    project_dir=self.project_dir,
                    restore_session=bool(self.session_id),
                )
                self.process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.project_dir,
                    creationflags=creationflags
                )
                self._receive_task = asyncio.create_task(self._receive_loop())
                self._stderr_task = asyncio.create_task(self._stderr_loop())

                init_resp = await self._send_request("initialize", {"protocolVersion": 0})
                if "error" in init_resp:
                    logger.error(f"ACP Initialize Failed: {init_resp['error']}")
                    return  # pragma: no cover

                if self.session_id:
                    session_resp = await self._send_request("session/load", {
                        "cwd": self.project_dir,
                        "mcpServers": [],
                        "sessionId": self.session_id
                    })
                    if "error" in session_resp:
                        log_event(
                            logger,
                            logging.WARNING,
                            "acp.session_load_failed",
                            session_id=self.session_id,
                            error=session_resp["error"],
                        )
                        self.session_id = None
                        self._persist_session_id()
                        session_resp = await self._send_request("session/new", {
                            "cwd": self.project_dir,
                            "mcpServers": []
                        })
                else:
                    session_resp = await self._send_request("session/new", {
                        "cwd": self.project_dir,
                        "mcpServers": []
                    })

                if "error" in session_resp:
                    logger.error(f"ACP Session Setup Failed: {session_resp['error']}")
                    return  # pragma: no cover

                result = session_resp.get("result", {})
                new_session_id = result.get("sessionId")
                if new_session_id:
                    self.session_id = new_session_id
                    self._persist_session_id()
                    logger.info(f"ACP 準備完成，Session ID: {self.session_id}")
                    self._ready_event.set()
                    startup_succeeded = True
                else:
                    logger.error("ACP Session 建立失敗，未取得 Session ID")  # pragma: no cover

            except Exception as e:
                logger.error(f"啟動 Gemini CLI ACP 失敗: {e}")  # pragma: no cover

            finally:
                if not startup_succeeded:
                    self._ready_event.clear()
                    self.session_id = None
                    self._persist_session_id()
                    await self._cleanup_failed_start()

    async def _send_request(self, method: str, params: dict):
        req_id = self._request_id
        self._request_id += 1
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": req_id
        }
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._response_futures[req_id] = future

        try:
            payload = json.dumps(msg) + "\n"
            log_event(logger, logging.DEBUG, "acp.request_sent", request_id=req_id, method=method)
            self.process.stdin.write(payload.encode('utf-8'))
            await self.process.stdin.drain()
            buffered_response = self._buffered_responses.pop(req_id, None)
            if buffered_response is not None and not future.done():
                future.set_result(buffered_response)
            return await future
        finally:
            if req_id in self._response_futures:  # pragma: no cover
                del self._response_futures[req_id]  # pragma: no cover

    async def _send_notification(self, method: str, params: dict):
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        payload = json.dumps(msg) + "\n"
        log_event(logger, logging.DEBUG, "acp.notification_sent", method=method)
        self.process.stdin.write(payload.encode("utf-8"))
        await self.process.stdin.drain()

    async def _stderr_loop(self):
        suppress_attach_console_trace = False
        try:
            while self.process and self.process.returncode is None:
                try:
                    line = await self.process.stderr.readline()
                except Exception as e:
                    logger.error(f"ACP STDERR Read Error: {e}")  # pragma: no cover
                    break

                if not line:
                    break

                if isinstance(line, (bytes, bytearray)):
                    text = line.decode("utf-8", errors="replace").strip()
                elif isinstance(line, str):
                    text = line.strip()
                else:
                    break

                if not text:
                    continue

                if "conpty_console_list_agent.js" in text or "AttachConsole failed" in text:
                    if not suppress_attach_console_trace:
                        log_event(
                            logger,
                            logging.DEBUG,
                            "acp.stderr_suppressed",
                            reason="attach_console_failed",
                        )
                    suppress_attach_console_trace = True
                    continue

                if suppress_attach_console_trace:
                    if (
                        text.startswith("at ")
                        or text.startswith("var consoleProcessList")
                        or text == "^"
                        or text.startswith("Node.js ")
                    ):
                        if text.startswith("Node.js "):
                            suppress_attach_console_trace = False
                        continue
                    suppress_attach_console_trace = False

                # node-pty can emit benign AttachConsole failures under CREATE_NO_WINDOW.
                if "AttachConsole failed" in text:
                    level = logging.DEBUG
                elif any(
                    token in text.lower()
                    for token in ("error", "failed", "exception", "warn")
                ):
                    level = logging.WARNING
                else:
                    level = logging.DEBUG
                log_event(logger, level, "acp.stderr", detail=text)
        except asyncio.CancelledError:
            raise

    async def _receive_loop(self):
        try:
            while self.process and self.process.returncode is None:
                try:
                    line = await self.process.stdout.readline()
                except Exception as e:
                    logger.error(f"ACP Read Error: {e}")  # pragma: no cover
                    break

                if not line:
                    break

                line_decoded = line.decode('utf-8', errors='replace').strip()
                log_event(logger, logging.DEBUG, "acp.stdout_received", bytes=len(line))
                if line_decoded:
                    logger.debug(f"ACP Raw: {line_decoded}")

                if not line_decoded:
                    continue

                try:
                    data = json.loads(line_decoded)
                    # Handle server requests that require a response.
                    if "id" in data and "method" in data:
                        await self._handle_server_request(data)
                        continue

                    # Handle responses to client requests.
                    if "id" in data:
                        req_id = data["id"]
                        if req_id in self._response_futures:
                            future = self._response_futures[req_id]
                            if not future.done():
                                future.set_result(data)
                            del self._response_futures[req_id]
                        else:
                            self._buffered_responses[req_id] = data
                        continue

                    # Handle notifications and stream updates.
                    if "method" in data:
                        if data["method"] == "session/update":
                            params = data.get("params", {})
                            if params.get("sessionId") == self.session_id:
                                update = params.get("update", {})
                                session_update_type = update.get("sessionUpdate", "")

                                # Surface tool failures that would otherwise be silent.
                                if session_update_type == "tool_call_update":
                                    if self.session_id in self._streaming_queues:
                                        queue = self._streaming_queues[self.session_id]
                                        self._mark_stream_replay_boundary(queue)
                                        self._enqueue_stream_chunk(queue, STREAM_ACTIVITY_KEEPALIVE)
                                    status = update.get("status", "")
                                    if status == "failed":
                                        tool_call_id = update.get("toolCallId", "unknown")
                                        title = update.get("title", "")
                                        content_list = update.get("content", [])
                                        error_detail = ""
                                        for item in content_list:
                                            if isinstance(item, dict) and item.get("type") == "content":
                                                inner = item.get("content", {})
                                                if isinstance(inner, dict):
                                                    error_detail = inner.get("text", "")[:200]
                                                    break
                                        log_event(
                                            logger,
                                            logging.WARNING,
                                            "acp.tool_call_failed",
                                            tool_call_id=tool_call_id,
                                            title=title,
                                            error_detail=error_detail,
                                        )

                                elif session_update_type == "agent_thought_chunk":
                                    if self.session_id in self._streaming_queues:
                                        queue = self._streaming_queues[self.session_id]
                                        self._mark_stream_replay_boundary(queue)
                                        self._enqueue_stream_chunk(queue, STREAM_ACTIVITY_KEEPALIVE)

                                elif session_update_type == "tool_call":
                                    if self.session_id in self._streaming_queues:
                                        queue = self._streaming_queues[self.session_id]
                                        self._mark_stream_replay_boundary(queue)
                                        self._enqueue_stream_chunk(queue, STREAM_ACTIVITY_KEEPALIVE)

                                elif session_update_type == "agent_message_chunk":
                                    chunk_text = update.get("content", {}).get("text", "")
                                    if chunk_text and self.session_id in self._streaming_queues:
                                        queue = self._streaming_queues[self.session_id]
                                        self._enqueue_stream_chunk(queue, chunk_text)

                except Exception as e:
                    logger.error(f"ACP Process Event Error: {e}")  # pragma: no cover
        finally:
            # Fail pending requests when the process exits unexpectedly.
            exit_code = getattr(self.process, "returncode", None)
            if exit_code not in (None, 0):
                log_event(logger, logging.WARNING, "acp.process_terminated", exit_code=exit_code)
            err = RuntimeError("Gemini CLI process terminated unexpectedly")
            for pending_future in list(self._response_futures.values()):
                if not pending_future.done():
                    pending_future.set_exception(err)

    async def _handle_server_request(self, data: dict):
        """Handle server requests such as tool permission prompts."""
        req_id = data.get("id")
        method = data.get("method")
        params = data.get("params", {})

        log_event(logger, logging.INFO, "acp.server_request_received", method=method, id=req_id)

        if method == "session/request_permission":
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "outcome": {
                        "outcome": "selected",
                        "optionId": "proceed_always",
                    }
                }
            }
            try:
                payload = json.dumps(response, ensure_ascii=False) + "\n"
                self.process.stdin.write(payload.encode('utf-8'))
                await self.process.stdin.drain()
                log_event(logger, logging.INFO, "acp.server_request_approved", method=method, id=req_id)
            except Exception as e:
                logger.error(f"Failed to respond to server request: {e}")
        else:
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }
            try:
                payload = json.dumps(response, ensure_ascii=False) + "\n"
                self.process.stdin.write(payload.encode('utf-8'))
                await self.process.stdin.drain()
            except Exception:
                pass

    async def send_message(self, text: str) -> AsyncGenerator[str, None]:
        self._cancel_flag = False
        started_here = False
        if not self.process or self.process.returncode is not None:
            self._ready_event.clear()
            started_here = True
            await self._start_acp()

        if not self._ready_event.is_set() and not self.session_id:
            log_event(logger, logging.WARNING, "acp.session_unavailable")
            if self.process and self.process.returncode is None and not self._ready_event.is_set():
                yield "等等哦！我還沒準備好！"
            else:
                yield "無法連線至本地 AI 助理。"
            return

        if started_here and not self._ready_event.is_set():
            log_event(logger, logging.WARNING, "acp.start_not_ready")
            yield "無法連線至本地 AI 助理。"
            return

        if not self._ready_event.is_set():
            try:
                await asyncio.wait_for(self._ready_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                log_event(logger, logging.WARNING, "acp.ready_timeout", session_id=self.session_id)
                yield "無法連線至本地 AI 助理。"
                return

        if not self.process or self.process.returncode is not None or not self.session_id:
            log_event(logger, logging.WARNING, "acp.session_unavailable")
            yield "無法連線至本地 AI 助理。"
            return

        queue = asyncio.Queue()
        queue.emitted_text = ""
        queue.replay_cursor = None
        self._streaming_queues[self.session_id] = queue

        self._active_prompt_req_id = self._request_id

        log_event(
            logger,
            logging.DEBUG,
            "acp.prompt_started",
            request_id=self._active_prompt_req_id,
            session_id=self.session_id,
            prompt_chars=len(text),
        )
        prompt_task = asyncio.create_task(self._send_request("session/prompt", {
            "sessionId": self.session_id,
            "prompt": [{"type": "text", "text": text}]
        }))

        queue_task = asyncio.create_task(queue.get())

        try:
            while True:
                if self._cancel_flag:
                    break

                done, pending = await asyncio.wait(
                    [prompt_task, queue_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                if queue_task in done:
                    chunk = queue_task.result()
                    yield chunk
                    queue_task = asyncio.create_task(queue.get())

                if prompt_task in done:
                    while not queue.empty():
                        if self._cancel_flag:
                            break  # pragma: no cover
                        yield queue.get_nowait()

                    resp = prompt_task.result()
                    if "error" in resp:
                        logger.error(f"Prompt Error: {resp['error']}")  # pragma: no cover
                        error_detail = resp["error"]
                        if isinstance(error_detail, dict):
                            error_message = error_detail.get("message") or json.dumps(
                                error_detail,
                                ensure_ascii=False,
                            )
                        else:
                            error_message = str(error_detail)
                        raise RuntimeError(f"Gemini CLI prompt failed: {error_message}")
                    break
        finally:
            if not queue_task.done():
                queue_task.cancel()
                try:
                    await queue_task
                except asyncio.CancelledError:
                    pass  # pragma: no cover
            if not prompt_task.done():
                prompt_task.cancel()
                try:
                    await prompt_task
                except asyncio.CancelledError:
                    pass  # pragma: no cover
            if self.session_id in self._streaming_queues:
                del self._streaming_queues[self.session_id]
            self._active_prompt_req_id = None

    async def cancel(self):
        self._cancel_flag = True
        if self.process and self.session_id and self._ready_event.is_set():
            try:
                target_id = self._active_prompt_req_id
                log_event(
                    logger,
                    logging.DEBUG,
                    "acp.cancel_requested",
                    session_id=self.session_id,
                    request_id=target_id,
                )
                await self._send_notification(
                    "session/cancel",
                    {"sessionId": self.session_id},
                )
                if target_id is not None:
                    await self._send_notification(
                        "$/cancelRequest",
                        {"requestId": target_id},
                    )
            except Exception:
                pass  # pragma: no cover

    async def aclose(self):
        self._cancel_flag = True
        try:
            await asyncio.wait_for(self.cancel(), timeout=1.0)
        except asyncio.TimeoutError:
            log_event(logger, logging.WARNING, "acp.cancel_timeout", timeout_seconds=1.0)
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "acp.cancel_failed_during_close",
                error_type=type(exc).__name__,
                error=str(exc),
            )

        await self._drain_task(self._receive_task, task_name="receive")
        await self._drain_task(self._stderr_task, task_name="stderr")

        for future in list(self._response_futures.values()):
            if not future.done():
                future.cancel()
        self._response_futures.clear()
        self._buffered_responses.clear()
        self._streaming_queues.clear()
        self._active_prompt_req_id = None

        if self.process and self.process.returncode is None:
            await self._terminate_process(self.process)

        self.process = None
        self._receive_task = None
        self._stderr_task = None
        self._ready_event.clear()

    async def refresh_session(self) -> bool:
        """Open a new conversation through ACP without restarting Node.js."""
        if not self.process or self.process.returncode is not None:
            self.session_id = None
            self._persist_session_id()
            await self._start_acp()  # pragma: no cover
            return bool(self.process and self.process.returncode is None and self.session_id)  # pragma: no cover

        log_event(logger, logging.INFO, "acp.session_refresh_started", session_id=self.session_id)
        self._ready_event.clear()
        try:
            session_resp = await self._send_request("session/new", {
                "cwd": self.project_dir,
                "mcpServers": []
            })

            if "error" in session_resp:
                logger.error(f"ACP Session 刷新失敗: {session_resp['error']}")
                return False  # pragma: no cover

            result = session_resp.get("result", {})
            new_session_id = result.get("sessionId")
            if new_session_id:
                self.session_id = new_session_id
                self._persist_session_id()
                log_event(logger, logging.INFO, "acp.session_refresh_completed", session_id=self.session_id)
                return True
            else:
                logger.error("ACP Session 刷新失敗，未取得 Session ID")  # pragma: no cover
                return False
        except Exception as e:
            logger.error(f"刷新 Session 發生錯誤: {e}")  # pragma: no cover
            return False
        finally:
            self._ready_event.set()

    async def ensure_ready(self) -> bool:
        if not self.process or self.process.returncode is not None:
            self._ready_event.clear()
            await self._start_acp()

        if not self._ready_event.is_set():
            await self._ready_event.wait()

        if not self.process or self.process.returncode is not None or not self.session_id:
            raise RuntimeError("無法連線至本地 AI 助理。")

        return True

    def __del__(self):
        if self.process and self.process.returncode is None:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass  # pragma: no cover
