import asyncio
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import AsyncGenerator

from .base_client import BaseLLMClient
from utils.logger import get_logger, log_event

logger = get_logger(__name__)

_CODEX_UNAVAILABLE_MESSAGE = "無法連線至本地 Codex 助理。"
_CODEX_LOGIN_REQUIRED_MESSAGE = "Codex CLI 尚未登入，請先在終端執行 codex login，再重新啟動。"


@dataclass(slots=True)
class _TurnStreamState:
    queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    item_phases: dict[str, str | None] = field(default_factory=dict)
    buffered_deltas: dict[str, list[str]] = field(default_factory=dict)
    error: Exception | None = None
    status: str | None = None
    turn_id: str | None = None
    interrupt_requested: bool = False

    @staticmethod
    def _should_stream_phase(phase: str | None) -> bool:
        return phase in (None, "final_answer")

    def register_item(self, item: dict | None):
        if not isinstance(item, dict):
            return

        item_id = item.get("id")
        if not item_id:
            return

        phase = item.get("phase")
        self.item_phases[item_id] = phase

        buffered = self.buffered_deltas.pop(item_id, None)
        if not buffered or not self._should_stream_phase(phase):
            return

        for chunk in buffered:
            self.queue.put_nowait(chunk)

    def add_delta(self, item_id: str | None, delta: str | None):
        if not item_id or not delta:
            return

        if item_id not in self.item_phases:
            self.buffered_deltas.setdefault(item_id, []).append(delta)
            return

        if self._should_stream_phase(self.item_phases[item_id]):
            self.queue.put_nowait(delta)

    def flush_unknown_deltas(self):
        for item_id, chunks in list(self.buffered_deltas.items()):
            phase = self.item_phases.get(item_id)
            if self._should_stream_phase(phase):
                for chunk in chunks:
                    self.queue.put_nowait(chunk)
            del self.buffered_deltas[item_id]


class CodexCLIClient(BaseLLMClient):
    """
    Maintain a Codex connection through the CLI app-server stdio transport.
    """

    def __init__(
        self,
        project_dir: str = "./",
        thread_id: str | None = None,
        model: str | None = None,
        reasoning_effort: str = "low",
        personality: str = "friendly",
        sandbox: str = "workspace-write",
        approval_policy: str = "on-request",
    ):
        self.project_dir = os.path.abspath(project_dir)
        os.makedirs(self.project_dir, exist_ok=True)

        self.thread_id = thread_id
        self.model = model or None
        self.reasoning_effort = reasoning_effort or "low"
        self.personality = personality or "friendly"
        self.sandbox = sandbox or "workspace-write"
        self.approval_policy = approval_policy or "on-request"

        self.process = None
        self._request_id = 1
        self._response_futures: dict[int, asyncio.Future] = {}
        self._buffered_responses: dict[int, dict] = {}
        self._receive_task = None
        self._stderr_task = None
        self._start_lock = None
        self._session_lock = None
        self._ready_event = asyncio.Event()
        self._cancel_flag = False
        self._auth_unavailable_message: str | None = None
        self._pending_turn_state: _TurnStreamState | None = None
        self._turn_states: dict[str, _TurnStreamState] = {}
        self._active_turn_id: str | None = None

    def _persist_thread_id(self):
        # Thread IDs are runtime-only state and should not be persisted to config.
        return

    def _get_session_lock(self) -> asyncio.Lock:
        if self._session_lock is None:
            self._session_lock = asyncio.Lock()
        return self._session_lock

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
                "codex.shutdown_task_timeout",
                task=task_name,
                timeout_seconds=timeout,
            )
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "codex.shutdown_task_failed",
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
                "codex.process_wait_timeout",
                timeout_seconds=timeout,
            )
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "codex.process_wait_failed",
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
        self._ready_event.clear()
        self._pending_turn_state = None
        self._active_turn_id = None
        self._turn_states.clear()

        for future in list(self._response_futures.values()):
            if not future.done():
                future.cancel()
        self._response_futures.clear()
        self._buffered_responses.clear()

        if process and process.returncode is None:
            await self._terminate_process(process)

    async def _start_server(self):
        if self._start_lock is None:
            self._start_lock = asyncio.Lock()

        async with self._start_lock:
            if self.process and self.process.returncode is None:
                log_event(logger, logging.DEBUG, "codex.start_skipped", reason="already_running")
                return

            codex_path = shutil.which("codex") or "codex"
            cmd = [codex_path, "app-server", "--listen", "stdio://"]
            creationflags = 0
            if sys.platform == "win32":
                import subprocess

                creationflags = subprocess.CREATE_NO_WINDOW

            startup_succeeded = False
            self._auth_unavailable_message = None

            try:
                log_event(
                    logger,
                    logging.DEBUG,
                    "codex.starting",
                    command=" ".join(cmd),
                    project_dir=self.project_dir,
                    restore_thread=bool(self.thread_id),
                )

                self.process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.project_dir,
                    creationflags=creationflags,
                )
                self._receive_task = asyncio.create_task(self._receive_loop())
                self._stderr_task = asyncio.create_task(self._stderr_loop())

                init_resp = await self._send_request(
                    "initialize",
                    {
                        "clientInfo": {
                            "name": "ai_voice_assistant",
                            "version": "2.2",
                            "title": "AI Voice Assistant",
                        },
                        "capabilities": {
                            "experimentalApi": False,
                        },
                    },
                )
                self._raise_for_error(init_resp, "Codex initialize failed")
                await self._send_notification("initialized")

                account_resp = await self._send_request("account/read", {"refreshToken": False})
                self._raise_for_error(account_resp, "Codex account/read failed")
                account_result = account_resp.get("result", {}) or {}
                if self._account_requires_login(account_result):
                    self._auth_unavailable_message = _CODEX_LOGIN_REQUIRED_MESSAGE
                    self._ready_event.set()
                    startup_succeeded = True
                    log_event(logger, logging.WARNING, "codex.auth_required")
                    return

                await self._maybe_populate_default_model()

                if self.thread_id:
                    try:
                        await self._resume_thread()
                    except RuntimeError as exc:
                        log_event(
                            logger,
                            logging.WARNING,
                            "codex.thread_resume_failed",
                            thread_id=self.thread_id,
                            error=str(exc),
                        )
                        self.thread_id = None
                        await self._start_thread()
                else:
                    await self._start_thread()

                self._ready_event.set()
                startup_succeeded = True
            except Exception as exc:
                logger.error(f"啟動 Codex CLI app-server 失敗: {exc}")
            finally:
                if not startup_succeeded:
                    self.thread_id = None
                    self._persist_thread_id()
                    await self._cleanup_failed_start()

    async def _maybe_populate_default_model(self):
        if self.model:
            return

        try:
            model_resp = await self._send_request("model/list", {"limit": 50, "includeHidden": False})
            if "error" in model_resp:
                return
            models = (model_resp.get("result", {}) or {}).get("data", [])
            selected = None
            for model in models:
                if model.get("isDefault"):
                    selected = model
                    break
            if selected is None and models:
                selected = next((model for model in models if not model.get("hidden")), models[0])
            if selected:
                self.model = selected.get("model") or selected.get("id") or self.model
        except Exception:
            logger.debug("Failed to fetch Codex default model.", exc_info=True)

    def _thread_start_params(self) -> dict:
        return {
            "cwd": self.project_dir,
            "model": self.model,
            "personality": self.personality,
            "sandbox": self.sandbox,
            "approvalPolicy": self.approval_policy,
        }

    async def _start_thread(self):
        response = await self._send_request("thread/start", self._thread_start_params())
        self._raise_for_error(response, "Codex thread/start failed")
        result = response.get("result", {}) or {}
        thread = result.get("thread", {}) or {}
        thread_id = thread.get("id")
        if not thread_id:
            raise RuntimeError("Codex thread/start did not return a thread id")
        self.thread_id = thread_id
        self._persist_thread_id()
        if not self.model:
            self.model = result.get("model") or self.model

    async def _resume_thread(self):
        params = self._thread_start_params()
        params["threadId"] = self.thread_id
        response = await self._send_request("thread/resume", params)
        self._raise_for_error(response, "Codex thread/resume failed")
        result = response.get("result", {}) or {}
        thread = result.get("thread", {}) or {}
        thread_id = thread.get("id") or self.thread_id
        if not thread_id:
            raise RuntimeError("Codex thread/resume did not return a thread id")
        self.thread_id = thread_id
        self._persist_thread_id()
        if not self.model:
            self.model = result.get("model") or self.model

    def _build_turn_sandbox_policy(self) -> dict | None:
        if self.sandbox == "danger-full-access":
            return {"type": "dangerFullAccess"}
        if self.sandbox == "workspace-write":
            return {"type": "workspaceWrite"}
        if self.sandbox == "read-only":
            return {"type": "readOnly"}
        return None

    async def _send_request(self, method: str, params: dict):
        if not self.process or self.process.stdin is None:
            raise RuntimeError("Codex CLI process is not available")

        req_id = self._request_id
        self._request_id += 1

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._response_futures[req_id] = future

        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        try:
            payload = json.dumps(msg, ensure_ascii=False) + "\n"
            log_event(logger, logging.DEBUG, "codex.request_sent", request_id=req_id, method=method)
            self.process.stdin.write(payload.encode("utf-8"))
            await self.process.stdin.drain()
            buffered_response = self._buffered_responses.pop(req_id, None)
            if buffered_response is not None and not future.done():
                future.set_result(buffered_response)
            return await future
        finally:
            self._response_futures.pop(req_id, None)

    async def _send_notification(self, method: str, params: dict | None = None):
        if not self.process or self.process.stdin is None:
            raise RuntimeError("Codex CLI process is not available")

        msg = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            msg["params"] = params

        payload = json.dumps(msg, ensure_ascii=False) + "\n"
        log_event(logger, logging.DEBUG, "codex.notification_sent", method=method)
        self.process.stdin.write(payload.encode("utf-8"))
        await self.process.stdin.drain()

    async def _send_error_response(self, request_id, message: str):
        if not self.process or self.process.stdin is None:
            return

        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": message,
                },
            },
            ensure_ascii=False,
        ) + "\n"
        self.process.stdin.write(payload.encode("utf-8"))
        await self.process.stdin.drain()

    async def _stderr_loop(self):
        try:
            while self.process and self.process.returncode is None:
                line = await self.process.stderr.readline()
                if not line:
                    break

                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue

                level = logging.WARNING if any(
                    token in text.lower()
                    for token in ("error", "failed", "exception", "warn")
                ) else logging.DEBUG
                log_event(logger, level, "codex.stderr", detail=text)
        except asyncio.CancelledError:
            raise

    async def _receive_loop(self):
        try:
            while self.process and self.process.returncode is None:
                line = await self.process.stdout.readline()
                if not line:
                    break

                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue

                log_event(logger, logging.DEBUG, "codex.stdout_received", bytes=len(line))

                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    log_event(logger, logging.DEBUG, "codex.stdout_non_json", detail=text)
                    continue

                if "id" in data and "method" in data:
                    await self._handle_server_request(data)
                    continue

                if "id" in data:
                    req_id = data["id"]
                    future = self._response_futures.get(req_id)
                    if future is not None:
                        if not future.done():
                            future.set_result(data)
                        self._response_futures.pop(req_id, None)
                    else:
                        self._buffered_responses[req_id] = data
                    continue

                if "method" in data:
                    await self._handle_notification(data["method"], data.get("params", {}) or {})
        finally:
            exit_code = getattr(self.process, "returncode", None)
            if exit_code not in (None, 0):
                log_event(logger, logging.WARNING, "codex.process_terminated", exit_code=exit_code)

            error = RuntimeError("Codex CLI process terminated unexpectedly")
            for future in list(self._response_futures.values()):
                if not future.done():
                    future.set_exception(error)

            if self._pending_turn_state is not None:
                if not self._pending_turn_state.done.is_set():
                    self._pending_turn_state.error = error
                    self._pending_turn_state.done.set()
                self._pending_turn_state = None

            for state in self._turn_states.values():
                if state.done.is_set():
                    continue
                state.error = error
                state.done.set()

    async def _handle_server_request(self, data: dict):
        request_id = data.get("id")
        method = data.get("method", "unknown")
        log_event(logger, logging.WARNING, "codex.server_request_received", method=method)
        if request_id is None:
            return
        try:
            await self._send_error_response(request_id, f"Unsupported server request: {method}")
        except Exception:
            logger.debug("Failed to reject Codex server request.", exc_info=True)

    async def _handle_notification(self, method: str, params: dict):
        if method == "turn/started":
            await self._handle_turn_started(params)
            return

        if method == "item/started":
            self._get_turn_state(params.get("turnId")).register_item(params.get("item"))
            return

        if method == "item/completed":
            self._get_turn_state(params.get("turnId")).register_item(params.get("item"))
            return

        if method == "item/agentMessage/delta":
            state = self._get_turn_state(params.get("turnId"))
            state.add_delta(params.get("itemId"), params.get("delta"))
            return

        if method == "turn/completed":
            turn = params.get("turn", {}) or {}
            turn_id = turn.get("id")
            state = self._get_turn_state(turn_id)
            state.status = turn.get("status")
            state.flush_unknown_deltas()
            if turn.get("status") == "failed":
                error_message = self._extract_turn_error_message(turn)
                state.error = RuntimeError(f"Codex CLI turn failed: {error_message}")
            state.done.set()
            if turn_id:
                self._turn_states.pop(turn_id, None)
                if self._active_turn_id == turn_id:
                    self._active_turn_id = None
            return

        if method == "account/updated":
            auth_mode = params.get("authMode")
            if auth_mode is None:
                if "authMode" in params:
                    self._auth_unavailable_message = _CODEX_LOGIN_REQUIRED_MESSAGE
            else:
                self._auth_unavailable_message = None
            return

    async def _handle_turn_started(self, params: dict):
        turn = params.get("turn", {}) or {}
        turn_id = turn.get("id")
        if not turn_id:
            return

        state = self._turn_states.get(turn_id)
        if state is None and self._pending_turn_state is not None:
            state = self._pending_turn_state
            self._pending_turn_state = None
            self._turn_states[turn_id] = state

        if state is None:
            state = _TurnStreamState()
            self._turn_states[turn_id] = state

        state.turn_id = turn_id
        self._active_turn_id = turn_id

        if state.interrupt_requested:
            await self._interrupt_turn(turn_id)

    def _get_turn_state(self, turn_id: str | None) -> _TurnStreamState:
        if turn_id and turn_id in self._turn_states:
            return self._turn_states[turn_id]

        if self._pending_turn_state is None:
            self._pending_turn_state = _TurnStreamState()

        if turn_id:
            self._pending_turn_state.turn_id = turn_id
            self._turn_states[turn_id] = self._pending_turn_state

        return self._pending_turn_state

    @staticmethod
    def _extract_error_message(payload: dict) -> str:
        error = payload.get("error")
        if isinstance(error, dict):
            return error.get("message") or json.dumps(error, ensure_ascii=False)
        if error is None:
            return ""
        return str(error)

    @staticmethod
    def _extract_turn_error_message(turn: dict) -> str:
        error = turn.get("error")
        if isinstance(error, dict):
            return error.get("message") or json.dumps(error, ensure_ascii=False)
        return "未知錯誤"

    @staticmethod
    def _account_requires_login(account_result: dict) -> bool:
        if not isinstance(account_result, dict):
            return True
        return bool(account_result.get("requiresOpenaiAuth")) and account_result.get("account") is None

    @classmethod
    def _raise_for_error(cls, payload: dict, fallback_message: str):
        if "error" not in payload:
            return
        message = cls._extract_error_message(payload)
        raise RuntimeError(message or fallback_message)

    async def _interrupt_turn(self, turn_id: str):
        if not self.thread_id or not turn_id:
            return
        try:
            await self._send_request(
                "turn/interrupt",
                {
                    "threadId": self.thread_id,
                    "turnId": turn_id,
                },
            )
        except Exception:
            logger.debug("Failed to interrupt Codex turn.", exc_info=True)

    async def send_message(self, text: str) -> AsyncGenerator[str, None]:
        self._cancel_flag = False
        started_here = False
        unavailable_message = None
        turn_state = None
        queue_task = None
        done_task = None
        try:
            async with self._get_session_lock():
                if not self.process or self.process.returncode is not None:
                    self._ready_event.clear()
                    started_here = True
                    await self._start_server()

                if self._auth_unavailable_message:
                    unavailable_message = self._auth_unavailable_message
                elif started_here and not self._ready_event.is_set():
                    unavailable_message = _CODEX_UNAVAILABLE_MESSAGE
                else:
                    if not self._ready_event.is_set():
                        try:
                            await asyncio.wait_for(self._ready_event.wait(), timeout=5.0)
                        except asyncio.TimeoutError:
                            unavailable_message = _CODEX_UNAVAILABLE_MESSAGE

                    if (
                        unavailable_message is None
                        and (
                            not self.process
                            or self.process.returncode is not None
                            or not self.thread_id
                        )
                    ):
                        unavailable_message = _CODEX_UNAVAILABLE_MESSAGE

                if unavailable_message is None:
                    turn_state = _TurnStreamState()
                    self._pending_turn_state = turn_state

                    params = {
                        "threadId": self.thread_id,
                        "input": [{"type": "text", "text": text}],
                        "cwd": self.project_dir,
                        "model": self.model,
                        "effort": self.reasoning_effort,
                        "personality": self.personality,
                        "approvalPolicy": self.approval_policy,
                        "sandboxPolicy": self._build_turn_sandbox_policy(),
                    }

                    response = await self._send_request("turn/start", params)
                    self._raise_for_error(response, "Codex turn/start failed")

                    turn = (response.get("result", {}) or {}).get("turn", {}) or {}
                    turn_id = turn.get("id")
                    if turn_id:
                        existing_state = self._turn_states.get(turn_id)
                        if existing_state is None:
                            turn_state.turn_id = turn_id
                            self._turn_states[turn_id] = turn_state
                        else:
                            turn_state = existing_state
                        self._pending_turn_state = None
                        self._active_turn_id = turn_id

                        if turn_state.interrupt_requested:
                            await self._interrupt_turn(turn_id)

            if unavailable_message is not None:
                yield unavailable_message
                return

            queue_task = asyncio.create_task(turn_state.queue.get())
            done_task = asyncio.create_task(turn_state.done.wait())

            while True:
                done, pending = await asyncio.wait(
                    [queue_task, done_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if queue_task in done:
                    chunk = queue_task.result()
                    yield chunk
                    queue_task = asyncio.create_task(turn_state.queue.get())

                if done_task in done:
                    while not turn_state.queue.empty():
                        yield turn_state.queue.get_nowait()
                    if turn_state.error is not None:
                        raise turn_state.error
                    break

        finally:
            for task in (queue_task, done_task):
                if task is None or task.done():
                    continue
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass  # pragma: no cover

            if turn_state is not None and self._pending_turn_state is turn_state:
                self._pending_turn_state = None

            if turn_state is not None:
                turn_id = turn_state.turn_id
                if turn_id and turn_id in self._turn_states and self._turn_states[turn_id] is turn_state:
                    if turn_state.done.is_set():
                        self._turn_states.pop(turn_id, None)

    async def cancel(self):
        self._cancel_flag = True
        turn_id = self._active_turn_id
        if turn_id:
            await self._interrupt_turn(turn_id)
            return

        if self._pending_turn_state is not None:
            self._pending_turn_state.interrupt_requested = True

    async def refresh_session(self) -> bool:
        async with self._get_session_lock():
            if not self.process or self.process.returncode is not None:
                self.thread_id = None
                self._persist_thread_id()
                await self._start_server()
                return bool(self.process and self.process.returncode is None and self.thread_id)

            if self._auth_unavailable_message:
                return False

            self.thread_id = None
            self._persist_thread_id()
            await self._start_thread()
            return bool(self.thread_id)

    async def ensure_ready(self) -> bool:
        async with self._get_session_lock():
            if not self.process or self.process.returncode is not None:
                self._ready_event.clear()
                await self._start_server()

            if self._auth_unavailable_message:
                raise RuntimeError(self._auth_unavailable_message)

            if not self._ready_event.is_set():
                await self._ready_event.wait()

            if not self.process or self.process.returncode is not None or not self.thread_id:
                raise RuntimeError(_CODEX_UNAVAILABLE_MESSAGE)

            return True

    async def aclose(self):
        try:
            await asyncio.wait_for(self.cancel(), timeout=1.0)
        except asyncio.TimeoutError:
            log_event(logger, logging.WARNING, "codex.cancel_timeout", timeout_seconds=1.0)
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "codex.cancel_failed_during_close",
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
        self._pending_turn_state = None
        self._turn_states.clear()
        self._active_turn_id = None

        if self.process and self.process.returncode is None:
            await self._terminate_process(self.process)

        self.process = None
        self._receive_task = None
        self._stderr_task = None
        self._ready_event.clear()

    def __del__(self):
        if self.process and self.process.returncode is None:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass  # pragma: no cover
