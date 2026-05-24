import asyncio
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import AsyncGenerator

from .base_client import BaseLLMClient, STREAM_ACTIVITY_KEEPALIVE
from utils.logger import get_logger, log_event

logger = get_logger(__name__)

_DEFAULT_UNAVAILABLE_MESSAGE = (
    "LLM backend is not ready. Please check that the CLI is installed and logged in."
)
_NORMAL_STOP_REASONS = {None, "", "end_turn"}
_CANCEL_STOP_REASONS = {"cancelled"}
_STDIO_BUFFER_LIMIT = 16 * 1024 * 1024
_PROMPT_KEEPALIVE_INTERVAL_SECONDS = 15.0


@dataclass(slots=True)
class _ACPStreamContext:
    queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    emitted_text: str = ""
    replay_cursor: int | None = None
    last_chunk: str | None = None


def _safe_short_text(value, *, limit: int = 240) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


class ACPStdioClient(BaseLLMClient):
    """
    Shared JSON-RPC ACP stdio client for long-lived CLI backends.

    The client intentionally logs request metadata only. It does not log raw
    ACP stdin/stdout payloads, prompts, assistant chunks, thoughts, tool raw
    input, or tool output.
    """

    unavailable_message = _DEFAULT_UNAVAILABLE_MESSAGE

    def __init__(
        self,
        *,
        backend_name: str,
        project_dir: str,
        executable_names: list[str],
        command_args: list[str],
        initialize_params: dict,
        supported_protocol_versions: set[int] | None = None,
        model: str | None = None,
        mode: str | None = None,
        permission_mode: str = "default",
        auto_approve: bool = False,
        required_context_files: list[str] | None = None,
        instruction_files: list[str] | None = None,
        shell: str | None = None,
        env_overrides: dict[str, str] | None = None,
        request_timeout_seconds: float = 30.0,
    ):
        self.backend_name = backend_name
        self.project_dir = os.path.abspath(project_dir)
        os.makedirs(self.project_dir, exist_ok=True)
        self.executable_names = list(executable_names)
        self.command_args = list(command_args)
        self.initialize_params = dict(initialize_params)
        self.supported_protocol_versions = supported_protocol_versions
        self.model = model or None
        self.mode = mode or None
        self.permission_mode = permission_mode or "default"
        self.auto_approve = bool(auto_approve)
        self.required_context_files = list(required_context_files or [])
        self.instruction_files = list(instruction_files or [])
        self.shell = shell or None
        self.env_overrides = dict(env_overrides or {})
        self.request_timeout_seconds = float(request_timeout_seconds)

        self.session_id: str | None = None
        self.process = None
        self._request_id = 1
        self._receive_task = None
        self._stderr_task = None
        self._start_lock = None
        self._ready_event = asyncio.Event()
        self._response_futures: dict[int, asyncio.Future] = {}
        self._buffered_responses: dict[int, dict] = {}
        self._streaming_queues: dict[str, _ACPStreamContext] = {}
        self._cancel_flag = False
        self._active_prompt_req_id: int | None = None
        self._agent_capabilities: dict = {}
        self._session_config_options: list | None = None

    def _persist_session_id(self) -> None:
        # Session IDs are runtime-only state and should not be persisted.
        return

    @staticmethod
    def _enqueue_stream_chunk(stream_context: _ACPStreamContext, chunk_text: str):
        if chunk_text == STREAM_ACTIVITY_KEEPALIVE:
            stream_context.queue.put_nowait(chunk_text)
            return

        normalized_chunk = ACPStdioClient._normalize_stream_chunk(stream_context, chunk_text)
        if normalized_chunk:
            stream_context.queue.put_nowait(normalized_chunk)

    @staticmethod
    def _mark_stream_replay_boundary(stream_context: _ACPStreamContext):
        if stream_context.emitted_text:
            stream_context.replay_cursor = 0

    @staticmethod
    def _normalize_stream_chunk(
        stream_context: _ACPStreamContext,
        chunk_text: str,
    ) -> str | None:
        if chunk_text == stream_context.last_chunk:
            log_event(logger, logging.DEBUG, "acp.chunk_skipped", reason="duplicate")
            return None

        stream_context.last_chunk = chunk_text
        emitted_text = stream_context.emitted_text
        replay_cursor = stream_context.replay_cursor

        if emitted_text and replay_cursor is not None:
            existing_slice = emitted_text[replay_cursor : replay_cursor + len(chunk_text)]
            if existing_slice == chunk_text:
                stream_context.replay_cursor = replay_cursor + len(chunk_text)
                log_event(logger, logging.DEBUG, "acp.chunk_skipped", reason="replayed_prefix")
                return None

            remaining_text = emitted_text[replay_cursor:]
            if remaining_text and chunk_text.startswith(remaining_text):
                suffix = chunk_text[len(remaining_text) :]
                stream_context.replay_cursor = len(emitted_text)
                if suffix:
                    stream_context.emitted_text = emitted_text + suffix
                    return suffix
                log_event(logger, logging.DEBUG, "acp.chunk_skipped", reason="replayed_prefix")
                return None

            stream_context.replay_cursor = None

        stream_context.emitted_text = emitted_text + chunk_text
        return chunk_text

    def _find_executable(self) -> str | None:
        for name in self.executable_names:
            resolved = shutil.which(name)
            if resolved:
                return resolved
        return None

    def _build_command(self) -> list[str]:
        executable = self._find_executable()
        if not executable:
            searched = ", ".join(self.executable_names)
            raise RuntimeError(f"{self.backend_name} executable was not found on PATH: {searched}")
        return [executable, *self.command_args]

    def _build_subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(self.env_overrides)
        return env

    def _before_start(self) -> None:
        return

    async def _drain_task(self, task, *, task_name: str, timeout: float = 1.0):
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except asyncio.CancelledError:
            pass
        except asyncio.TimeoutError:
            log_event(
                logger,
                logging.WARNING,
                "acp.shutdown_task_timeout",
                backend=self.backend_name,
                task=task_name,
                timeout_seconds=timeout,
            )
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "acp.shutdown_task_failed",
                backend=self.backend_name,
                task=task_name,
                error_type=type(exc).__name__,
                error=_safe_short_text(exc),
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
                backend=self.backend_name,
                timeout_seconds=timeout,
            )
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "acp.process_wait_failed",
                backend=self.backend_name,
                error_type=type(exc).__name__,
                error=_safe_short_text(exc),
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

            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/T",
                    "/F",
                    "/PID",
                    str(pid),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                await asyncio.wait_for(killer.wait(), timeout=5.0)
            except Exception:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        else:
            try:
                process.kill()
            except ProcessLookupError:
                pass

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
        self._agent_capabilities = {}
        self._session_config_options = None

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
            if self.process and self.process.returncode is None and self._ready_event.is_set():
                log_event(
                    logger,
                    logging.DEBUG,
                    "acp.start_skipped",
                    backend=self.backend_name,
                    reason="already_running",
                )
                return

            if self.process and self.process.returncode is None and not self._ready_event.is_set():
                return

            startup_succeeded = False
            self._ready_event.clear()
            self._before_start()
            cmd = self._build_command()

            creationflags = 0
            if sys.platform == "win32":
                import subprocess

                creationflags = subprocess.CREATE_NO_WINDOW

            try:
                log_event(
                    logger,
                    logging.INFO,
                    "acp.starting",
                    backend=self.backend_name,
                    executable=os.path.basename(cmd[0]),
                    project_dir=self.project_dir,
                    restore_session=bool(self.session_id),
                )
                self.process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.project_dir,
                    env=self._build_subprocess_env(),
                    limit=_STDIO_BUFFER_LIMIT,
                    creationflags=creationflags,
                )
                self._receive_task = asyncio.create_task(self._receive_loop())
                self._stderr_task = asyncio.create_task(self._stderr_loop())

                init_resp = await self._send_request(
                    "initialize",
                    self.initialize_params,
                    timeout=self.request_timeout_seconds,
                )
                self._handle_response_error(init_resp, "initialize")
                self._validate_initialize_response(init_resp)

                init_result = init_resp.get("result", {})
                if isinstance(init_result, dict):
                    self._agent_capabilities = init_result.get("agentCapabilities") or {}

                await self._setup_session()
                self._ready_event.set()
                startup_succeeded = True
                log_event(
                    logger,
                    logging.INFO,
                    "acp.ready",
                    backend=self.backend_name,
                    session_id=self.session_id,
                )
            except Exception:
                self._ready_event.clear()
                await self._cleanup_failed_start()
                raise
            finally:
                if not startup_succeeded:
                    self._ready_event.clear()

    def _validate_initialize_response(self, response: dict) -> None:
        if self.supported_protocol_versions is None:
            return
        result = response.get("result", {})
        protocol_version = result.get("protocolVersion") if isinstance(result, dict) else None
        if protocol_version not in self.supported_protocol_versions:
            supported = ", ".join(str(v) for v in sorted(self.supported_protocol_versions))
            raise RuntimeError(
                f"{self.backend_name} ACP protocol version {protocol_version!r} is not supported. "
                f"Supported: {supported}."
            )

    def _supports_session_capability(self, name: str) -> bool:
        capabilities = self._agent_capabilities or {}
        session_capabilities = capabilities.get("sessionCapabilities") or {}
        if isinstance(session_capabilities, dict) and session_capabilities.get(name):
            return True
        return bool(capabilities.get(name))

    async def _setup_session(self) -> None:
        restored = False
        config_options = None

        if self.session_id:
            method = None
            if self._supports_session_capability("resume"):
                method = "session/resume"
            elif self._agent_capabilities.get("loadSession"):
                method = "session/load"

            if method:
                resp = await self._send_request(
                    method,
                    {
                        "cwd": self.project_dir,
                        "mcpServers": [],
                        "sessionId": self.session_id,
                    },
                    timeout=self.request_timeout_seconds,
                )
                if "error" in resp:
                    log_event(
                        logger,
                        logging.WARNING,
                        "acp.session_restore_failed",
                        backend=self.backend_name,
                        method=method,
                        session_id=self.session_id,
                        error=self._format_response_error(resp),
                    )
                    self.session_id = None
                    self._persist_session_id()
                else:
                    result = resp.get("result")
                    if isinstance(result, dict) and result.get("sessionId"):
                        self.session_id = result["sessionId"]
                        self._persist_session_id()
                    config_options = result.get("configOptions") if isinstance(result, dict) else None
                    restored = True
                    log_event(
                        logger,
                        logging.INFO,
                        "acp.session_restored",
                        backend=self.backend_name,
                        method=method,
                        session_id=self.session_id,
                        has_config_options=config_options is not None,
                    )

                    if config_options is None and (self.model or self.mode):
                        log_event(
                            logger,
                            logging.INFO,
                            "acp.session_restore_requires_config_options",
                            backend=self.backend_name,
                            method=method,
                        )
                        restored = False
                        self.session_id = None
                        self._persist_session_id()

        if not self.session_id or not restored:
            resp = await self._send_request(
                "session/new",
                {
                    "cwd": self.project_dir,
                    "mcpServers": [],
                },
                timeout=self.request_timeout_seconds,
            )
            self._handle_response_error(resp, "session/new")
            result = resp.get("result", {})
            if not isinstance(result, dict) or not result.get("sessionId"):
                raise RuntimeError(f"{self.backend_name} ACP session/new did not return a sessionId.")
            self.session_id = result["sessionId"]
            self._persist_session_id()
            config_options = result.get("configOptions")
            restored = False
            log_event(
                logger,
                logging.INFO,
                "acp.session_created",
                backend=self.backend_name,
                session_id=self.session_id,
                has_config_options=config_options is not None,
            )

        self._session_config_options = config_options if isinstance(config_options, list) else None
        await self._apply_session_config_options(config_options)

    async def _apply_session_config_options(self, config_options):
        if not self.model and not self.mode:
            return
        if not self.session_id:
            raise RuntimeError(f"{self.backend_name} ACP session is unavailable.")
        if not isinstance(config_options, list):
            raise RuntimeError(
                f"{self.backend_name} ACP did not provide configOptions required to set model or mode."
            )

        if self.model:
            await self._set_config_option(config_options, "model", self.model)
        if self.mode:
            await self._set_config_option(config_options, "mode", self.mode)

    async def _set_config_option(self, config_options: list, config_id: str, value: str):
        option = self._find_config_option(config_options, config_id)
        if option is None:
            raise RuntimeError(
                f"{self.backend_name} ACP config option '{config_id}' is not available."
            )

        available_values = self._config_option_values(option)
        if available_values and value not in available_values:
            preview = ", ".join(available_values[:8])
            if len(available_values) > 8:
                preview += ", ..."
            raise RuntimeError(
                f"{self.backend_name} {config_id} '{value}' is not available. "
                f"Available values: {preview}"
            )

        resp = await self._send_request(
            "session/set_config_option",
            {
                "sessionId": self.session_id,
                "configId": config_id,
                "value": value,
            },
            timeout=self.request_timeout_seconds,
        )
        self._handle_response_error(resp, f"session/set_config_option:{config_id}")
        log_event(
            logger,
            logging.INFO,
            "acp.config_option_set",
            backend=self.backend_name,
            session_id=self.session_id,
            config_id=config_id,
        )

    @staticmethod
    def _find_config_option(config_options: list, config_id: str):
        for option in config_options:
            if isinstance(option, dict) and option.get("id") == config_id:
                return option
        return None

    @staticmethod
    def _config_option_values(option: dict) -> list[str]:
        values = []
        for item in option.get("options") or []:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, dict):
                raw = item.get("value", item.get("id"))
                if raw is not None:
                    values.append(str(raw))
        return values

    def _format_response_error(self, response: dict) -> str:
        error = response.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            message = _safe_short_text(error.get("message"), limit=260)
            if code is not None and message:
                return f"code={code} message={message}"
            if message:
                return message
            return _safe_short_text(error, limit=260)
        return _safe_short_text(error, limit=260)

    def _handle_response_error(self, response: dict, method: str) -> None:
        if "error" not in response:
            return
        error = self._format_response_error(response)
        log_event(
            logger,
            logging.WARNING,
            "acp.response_error",
            backend=self.backend_name,
            method=method,
            error=error,
        )
        raise RuntimeError(f"{self.backend_name} ACP {method} failed: {error}")

    async def _send_request(
        self,
        method: str,
        params: dict,
        *,
        timeout: float | None = None,
    ) -> dict:
        if not self.process or not getattr(self.process, "stdin", None):
            raise RuntimeError(f"{self.backend_name} ACP process is not running.")

        req_id = self._request_id
        self._request_id += 1
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": req_id,
        }
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._response_futures[req_id] = future

        try:
            payload = json.dumps(msg, ensure_ascii=False) + "\n"
            log_event(
                logger,
                logging.DEBUG,
                "acp.request_sent",
                backend=self.backend_name,
                request_id=req_id,
                method=method,
                session_id=params.get("sessionId") if isinstance(params, dict) else None,
                prompt_chars=self._prompt_chars(params) if method == "session/prompt" else None,
            )
            self.process.stdin.write(payload.encode("utf-8"))
            await self.process.stdin.drain()

            buffered_response = self._buffered_responses.pop(req_id, None)
            if buffered_response is not None and not future.done():
                future.set_result(buffered_response)

            if timeout is None:
                return await future
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._response_futures.pop(req_id, None)

    @staticmethod
    def _prompt_chars(params: dict | None) -> int | None:
        if not isinstance(params, dict):
            return None
        prompt = params.get("prompt")
        if not isinstance(prompt, list):
            return None
        total = 0
        for item in prompt:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                total += len(item["text"])
        return total

    async def _send_notification(self, method: str, params: dict):
        if not self.process or not getattr(self.process, "stdin", None):
            return
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        payload = json.dumps(msg, ensure_ascii=False) + "\n"
        log_event(
            logger,
            logging.DEBUG,
            "acp.notification_sent",
            backend=self.backend_name,
            method=method,
            session_id=params.get("sessionId") if isinstance(params, dict) else None,
        )
        self.process.stdin.write(payload.encode("utf-8"))
        await self.process.stdin.drain()

    async def _send_server_response(self, req_id, payload: dict):
        if not self.process or not getattr(self.process, "stdin", None):
            return
        response = {"jsonrpc": "2.0", "id": req_id, **payload}
        self.process.stdin.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        await self.process.stdin.drain()

    async def _stderr_loop(self):
        try:
            while self.process and self.process.returncode is None:
                line = await self.process.stderr.readline()
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

                lower = text.lower()
                level = logging.WARNING if any(t in lower for t in ("error", "failed", "exception", "warn")) else logging.DEBUG
                log_event(
                    logger,
                    level,
                    "acp.stderr",
                    backend=self.backend_name,
                    chars=len(text),
                    has_error_keyword=level >= logging.WARNING,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_event(
                logger,
                logging.DEBUG,
                "acp.stderr_read_failed",
                backend=self.backend_name,
                error_type=type(exc).__name__,
            )

    async def _receive_loop(self):
        try:
            while self.process and self.process.returncode is None:
                try:
                    line = await self.process.stdout.readline()
                except Exception as exc:
                    log_event(
                        logger,
                        logging.WARNING,
                        "acp.stdout_read_failed",
                        backend=self.backend_name,
                        error_type=type(exc).__name__,
                        error=_safe_short_text(exc),
                    )
                    break

                if not line:
                    break

                try:
                    decoded = line.decode("utf-8", errors="replace").strip()
                except AttributeError:
                    decoded = str(line).strip()

                log_event(
                    logger,
                    logging.DEBUG,
                    "acp.stdout_received",
                    backend=self.backend_name,
                    bytes=len(line) if hasattr(line, "__len__") else None,
                )
                if not decoded:
                    continue

                try:
                    data = json.loads(decoded)
                except json.JSONDecodeError:
                    log_event(logger, logging.DEBUG, "acp.stdout_non_json", backend=self.backend_name)
                    continue

                if "id" in data and "method" in data:
                    await self._handle_server_request(data)
                    continue

                if "id" in data:
                    req_id = data["id"]
                    future = self._response_futures.get(req_id)
                    if future is not None and not future.done():
                        future.set_result(data)
                    else:
                        self._buffered_responses[req_id] = data
                    continue

                if data.get("method") == "session/update":
                    self._handle_session_update(data.get("params", {}))
                elif "method" in data:
                    log_event(
                        logger,
                        logging.DEBUG,
                        "acp.notification_ignored",
                        backend=self.backend_name,
                        method=data.get("method"),
                    )
        except asyncio.CancelledError:
            raise
        finally:
            exit_code = getattr(self.process, "returncode", None)
            if exit_code not in (None, 0):
                log_event(
                    logger,
                    logging.WARNING,
                    "acp.process_terminated",
                    backend=self.backend_name,
                    exit_code=exit_code,
                )
            err = RuntimeError(f"{self.backend_name} ACP process terminated unexpectedly")
            for pending_future in list(self._response_futures.values()):
                if not pending_future.done():
                    pending_future.set_exception(err)

    def _handle_session_update(self, params: dict):
        if not isinstance(params, dict):
            return
        session_id = params.get("sessionId")
        update = params.get("update", {})
        if not isinstance(update, dict):
            return
        update_type = update.get("sessionUpdate") or update.get("type") or ""
        log_event(
            logger,
            logging.DEBUG,
            "acp.session_update",
            backend=self.backend_name,
            session_id=session_id,
            update_type=update_type,
        )

        stream_context = self._streaming_queues.get(session_id)
        if stream_context is None:
            return

        if update_type == "agent_message_chunk":
            content = update.get("content", {})
            text = content.get("text") if isinstance(content, dict) else None
            if text:
                self._enqueue_stream_chunk(stream_context, str(text))
            return

        if update_type in {"agent_thought_chunk", "tool_call", "tool_call_update"}:
            self._mark_stream_replay_boundary(stream_context)
            self._enqueue_stream_chunk(stream_context, STREAM_ACTIVITY_KEEPALIVE)
            if update_type == "tool_call_update" and update.get("status") == "failed":
                log_event(
                    logger,
                    logging.WARNING,
                    "acp.tool_call_failed",
                    backend=self.backend_name,
                    session_id=session_id,
                    tool_call_id=update.get("toolCallId"),
                    title=_safe_short_text(update.get("title"), limit=80),
                )

    async def _handle_server_request(self, data: dict):
        req_id = data.get("id")
        method = data.get("method")
        params = data.get("params", {}) if isinstance(data.get("params", {}), dict) else {}
        log_event(
            logger,
            logging.INFO,
            "acp.server_request_received",
            backend=self.backend_name,
            method=method,
            id=req_id,
        )

        if method == "session/request_permission":
            await self._handle_permission_request(req_id, params)
            return

        await self._send_server_response(
            req_id,
            {
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                }
            },
        )

    async def _handle_permission_request(self, req_id, params: dict):
        selected_option = None
        if self.auto_approve and not self._cancel_flag:
            selected_option = self._select_allow_permission_option(params.get("options") or [])

        if selected_option:
            outcome = {"outcome": "selected", "optionId": selected_option}
            event = "acp.server_request_approved"
        else:
            outcome = {"outcome": "cancelled"}
            event = "acp.server_request_cancelled"

        await self._send_server_response(req_id, {"result": {"outcome": outcome}})
        log_event(
            logger,
            logging.INFO,
            event,
            backend=self.backend_name,
            method="session/request_permission",
            id=req_id,
            selected=bool(selected_option),
        )

    @staticmethod
    def _select_allow_permission_option(options) -> str | None:
        normalized = []
        for option in options if isinstance(options, list) else []:
            if isinstance(option, str):
                normalized.append({"optionId": option, "kind": option})
            elif isinstance(option, dict):
                option_id = option.get("optionId") or option.get("id")
                if option_id:
                    normalized.append(
                        {
                            "optionId": str(option_id),
                            "kind": str(option.get("kind") or ""),
                        }
                    )

        def first_matching(predicate):
            for item in normalized:
                if predicate(item):
                    return item["optionId"]
            return None

        return (
            first_matching(lambda item: item["kind"] == "allow_always")
            or first_matching(lambda item: item["kind"] == "allow_once")
            or first_matching(
                lambda item: any(
                    token in item["optionId"].lower()
                    for token in ("proceed_always", "allow-always", "allow_always")
                )
            )
            or first_matching(
                lambda item: any(
                    token in f"{item['optionId']} {item['kind']}".lower()
                    for token in ("allow", "proceed")
                )
            )
        )

    async def send_message(self, text: str) -> AsyncGenerator[str, None]:
        self._cancel_flag = False

        try:
            await self.ensure_ready()
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "acp.send_unavailable",
                backend=self.backend_name,
                error_type=type(exc).__name__,
            )
            yield self.unavailable_message
            return

        if not self.process or self.process.returncode is not None or not self.session_id:
            log_event(logger, logging.WARNING, "acp.session_unavailable", backend=self.backend_name)
            yield self.unavailable_message
            return

        stream_context = _ACPStreamContext()
        queue = stream_context.queue
        session_id = self.session_id
        self._streaming_queues[session_id] = stream_context
        self._active_prompt_req_id = self._request_id

        prompt_task = asyncio.create_task(
            self._send_request(
                "session/prompt",
                {
                    "sessionId": session_id,
                    "prompt": [{"type": "text", "text": text}],
                },
            )
        )
        queue_task = asyncio.create_task(queue.get())
        keepalive_task = asyncio.create_task(
            asyncio.sleep(_PROMPT_KEEPALIVE_INTERVAL_SECONDS)
        )

        try:
            while True:
                if self._cancel_flag:
                    break

                done, _pending = await asyncio.wait(
                    [prompt_task, queue_task, keepalive_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if queue_task in done:
                    chunk = queue_task.result()
                    yield chunk
                    queue_task = asyncio.create_task(queue.get())

                if keepalive_task in done:
                    if not prompt_task.done():
                        yield STREAM_ACTIVITY_KEEPALIVE
                        keepalive_task = asyncio.create_task(
                            asyncio.sleep(_PROMPT_KEEPALIVE_INTERVAL_SECONDS)
                        )

                if prompt_task in done:
                    while not queue.empty():
                        if self._cancel_flag:
                            break
                        yield queue.get_nowait()

                    resp = prompt_task.result()
                    self._handle_response_error(resp, "session/prompt")
                    self._handle_prompt_stop_reason(resp)
                    break
        finally:
            if not queue_task.done():
                queue_task.cancel()
                try:
                    await queue_task
                except asyncio.CancelledError:
                    pass
            if not keepalive_task.done():
                keepalive_task.cancel()
                try:
                    await keepalive_task
                except asyncio.CancelledError:
                    pass
            if not prompt_task.done():
                prompt_task.cancel()
                try:
                    await prompt_task
                except asyncio.CancelledError:
                    pass
            self._streaming_queues.pop(session_id, None)
            self._active_prompt_req_id = None

    def _handle_prompt_stop_reason(self, response: dict) -> None:
        result = response.get("result", {})
        stop_reason = result.get("stopReason") if isinstance(result, dict) else None
        if stop_reason in _NORMAL_STOP_REASONS:
            return
        if stop_reason in _CANCEL_STOP_REASONS and self._cancel_flag:
            return
        log_event(
            logger,
            logging.WARNING,
            "acp.prompt_non_normal_stop",
            backend=self.backend_name,
            stop_reason=stop_reason,
        )
        raise RuntimeError(f"{self.backend_name} ACP prompt stopped: {stop_reason}")

    async def cancel(self):
        self._cancel_flag = True
        if not self.process or not self.session_id or not self._ready_event.is_set():
            return

        target_id = self._active_prompt_req_id
        log_event(
            logger,
            logging.DEBUG,
            "acp.cancel_requested",
            backend=self.backend_name,
            session_id=self.session_id,
            request_id=target_id,
        )
        try:
            await self._send_notification("session/cancel", {"sessionId": self.session_id})
        except Exception as exc:
            log_event(
                logger,
                logging.DEBUG,
                "acp.session_cancel_failed",
                backend=self.backend_name,
                error_type=type(exc).__name__,
            )

        if target_id is not None:
            try:
                await self._send_notification("$/cancelRequest", {"requestId": target_id})
            except Exception as exc:
                log_event(
                    logger,
                    logging.DEBUG,
                    "acp.request_cancel_failed",
                    backend=self.backend_name,
                    request_id=target_id,
                    error_type=type(exc).__name__,
                )

    async def refresh_session(self) -> bool:
        if not self.process or self.process.returncode is not None:
            self.session_id = None
            self._persist_session_id()
            try:
                await self._start_acp()
            except Exception as exc:
                log_event(
                    logger,
                    logging.WARNING,
                    "acp.session_refresh_start_failed",
                    backend=self.backend_name,
                    error_type=type(exc).__name__,
                )
                return False
            return bool(self.process and self.process.returncode is None and self.session_id)

        old_session_id = self.session_id
        self._ready_event.clear()
        try:
            resp = await self._send_request(
                "session/new",
                {"cwd": self.project_dir, "mcpServers": []},
                timeout=self.request_timeout_seconds,
            )
            self._handle_response_error(resp, "session/new")
            result = resp.get("result", {})
            if not isinstance(result, dict) or not result.get("sessionId"):
                return False
            self.session_id = result["sessionId"]
            self._persist_session_id()
            await self._apply_session_config_options(result.get("configOptions"))
            self._ready_event.set()
            log_event(
                logger,
                logging.INFO,
                "acp.session_refresh_completed",
                backend=self.backend_name,
                session_id=self.session_id,
            )
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "acp.session_refresh_failed",
                backend=self.backend_name,
                error_type=type(exc).__name__,
                error=_safe_short_text(exc),
            )
            self._ready_event.set()
            return False

        if old_session_id and self._supports_session_capability("close"):
            try:
                await self._send_request(
                    "session/close",
                    {"sessionId": old_session_id},
                    timeout=min(self.request_timeout_seconds, 5.0),
                )
            except Exception as exc:
                log_event(
                    logger,
                    logging.DEBUG,
                    "acp.session_close_failed",
                    backend=self.backend_name,
                    session_id=old_session_id,
                    error_type=type(exc).__name__,
                )
        return True

    async def ensure_ready(self) -> bool:
        if not self.process or self.process.returncode is not None:
            await self._start_acp()

        if not self._ready_event.is_set():
            try:
                await asyncio.wait_for(self._ready_event.wait(), timeout=self.request_timeout_seconds)
            except asyncio.TimeoutError as exc:
                raise RuntimeError(f"{self.backend_name} ACP startup timed out.") from exc

        if not self.process or self.process.returncode is not None or not self.session_id:
            raise RuntimeError(f"{self.backend_name} ACP session is unavailable.")
        return True

    async def aclose(self):
        self._cancel_flag = True
        try:
            await asyncio.wait_for(self.cancel(), timeout=1.0)
        except Exception:
            pass

        if self.process and self.session_id and self._supports_session_capability("close"):
            try:
                await self._send_request(
                    "session/close",
                    {"sessionId": self.session_id},
                    timeout=2.0,
                )
            except Exception as exc:
                log_event(
                    logger,
                    logging.DEBUG,
                    "acp.session_close_failed",
                    backend=self.backend_name,
                    session_id=self.session_id,
                    error_type=type(exc).__name__,
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
