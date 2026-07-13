import logging
import os
import shutil
import tempfile
from pathlib import Path

from .acp_stdio_client import ACPStdioClient
from utils.logger import get_logger, log_event
from utils.value_parsing import parse_bool

logger = get_logger(__name__)

APP_DIR = Path(__file__).resolve().parents[1]
AGENT_WORKSPACE_TEMPLATE_DIR = APP_DIR / "agent_workspace_template"


def _resolve_project_dir(project_dir: str) -> Path:
    raw = Path(project_dir or "./agent_workspace")
    if raw.is_absolute():
        return raw.resolve()
    return (APP_DIR / raw).resolve()


class GrokCLIClient(ACPStdioClient):
    """Grok Build ACP backend using ``grok agent stdio``."""

    unavailable_message = (
        "Grok Build backend 尚未就緒，請確認 Grok Build 已安裝、已登入，"
        "且 agent_workspace 的 AGENTS.md / MEMORY.md 可讀取。"
    )

    def __init__(
        self,
        project_dir: str = "./agent_workspace",
        executable: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        auth_method: str = "auto",
        auto_approve: bool = True,
        auto_approve_scope: str = "once",
        enable_web_search: bool = True,
        enable_subagents: bool = False,
        load_private_context: bool = True,
        required_context_files: list[str] | None = None,
        instruction_files: list[str] | None = None,
        env_overrides: dict[str, str] | None = None,
        request_timeout_seconds: float = 30.0,
    ):
        resolved_project_dir = _resolve_project_dir(project_dir)
        fallback_executable = Path.home() / ".grok" / "bin" / "grok.exe"

        self.executable = str(executable or "").strip() or None
        self.reasoning_effort = str(reasoning_effort or "").strip() or None
        self.auth_method = str(auth_method or "auto").strip() or "auto"
        self.enable_web_search = parse_bool(enable_web_search, default=True)
        self.enable_subagents = parse_bool(enable_subagents, default=False)
        self.load_private_context = parse_bool(load_private_context, default=True)
        self._agent_profile_path: Path | None = None

        executable_names = []
        if self.executable:
            executable_names.append(self.executable)
        executable_names.extend(
            [
                str(fallback_executable),
                "grok.exe",
                "grok.cmd",
                "grok",
            ]
        )

        super().__init__(
            backend_name="grok",
            project_dir=str(resolved_project_dir),
            executable_names=executable_names,
            command_args=[],
            initialize_params={
                "protocolVersion": 1,
                "clientCapabilities": {},
                "clientInfo": {
                    "name": "ai-governess",
                    "title": "AI Governess Voice Assistant",
                    "version": "2.5",
                },
            },
            supported_protocol_versions={1},
            model=model or None,
            permission_mode="default",
            auto_approve=auto_approve,
            auto_approve_scope=auto_approve_scope,
            stream_mode="final_segment",
            required_context_files=required_context_files or ["AGENTS.md"],
            instruction_files=instruction_files or ["MEMORY.md"],
            env_overrides=env_overrides or {},
            request_timeout_seconds=request_timeout_seconds,
        )

    def _find_executable(self) -> str | None:
        for name in self.executable_names:
            candidate = Path(name).expanduser()
            if candidate.is_absolute() and candidate.is_file():
                return str(candidate)
            resolved = shutil.which(name)
            if resolved:
                return resolved
        return None

    def _before_start(self) -> None:
        self._cleanup_agent_profile()
        if self.load_private_context:
            self._bootstrap_private_workspace_files()
        profile_path = self._create_agent_profile(include_context=self.load_private_context)

        args = ["--no-auto-update", "--no-memory", "agent"]
        if self.model:
            args.extend(["--model", self.model])
        if self.reasoning_effort:
            args.extend(["--reasoning-effort", self.reasoning_effort])
        if profile_path:
            args.extend(["--agent-profile", str(profile_path)])
        args.append("stdio")
        self.command_args = args

    def _bootstrap_private_workspace_files(self) -> None:
        project_dir = Path(self.project_dir)
        project_dir.mkdir(parents=True, exist_ok=True)
        if not AGENT_WORKSPACE_TEMPLATE_DIR.exists():
            log_event(
                logger,
                logging.WARNING,
                "grok.context_template_missing",
                template_dir=str(AGENT_WORKSPACE_TEMPLATE_DIR),
            )
            return

        seen: set[str] = set()
        for rel_path in [*self.required_context_files, *self.instruction_files]:
            rel = str(rel_path or "").strip()
            if not rel or rel in seen:
                continue
            seen.add(rel)
            source = AGENT_WORKSPACE_TEMPLATE_DIR / rel
            destination = project_dir / rel
            if destination.exists() or not source.is_file():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            log_event(
                logger,
                logging.INFO,
                "grok.context_bootstrap_file",
                path=str(destination),
                template=str(source),
            )

    def _create_agent_profile(self, *, include_context: bool = True) -> Path:
        project_dir = Path(self.project_dir)
        context_sections: list[str] = []
        seen: set[str] = set()

        context_paths = (
            [*self.required_context_files, *self.instruction_files]
            if include_context
            else []
        )
        for rel_path in context_paths:
            rel = str(rel_path or "").strip()
            if not rel or rel in seen:
                continue
            seen.add(rel)
            path = project_dir / rel
            exists = path.is_file()
            required = rel in self.required_context_files
            log_event(
                logger,
                logging.INFO if exists else logging.WARNING,
                "grok.context_file",
                path=str(path),
                exists=exists,
                required=required,
            )
            if not exists:
                if required:
                    raise RuntimeError(f"Grok required context file is missing: {path}")
                continue
            text = path.read_text(encoding="utf-8")
            context_sections.append(
                f"## Runtime context: {rel}\n\n{text.rstrip()}\n"
            )

        disallowed_tools = []
        if not self.enable_web_search:
            disallowed_tools.extend(["web_search", "web_fetch", "x_search"])

        frontmatter = [
            "---",
            "name: ai-governess-runtime",
            "description: Private runtime profile for AI Governess.",
            "prompt_mode: full",
            "permission_mode: default",
            "agents_md: false",
        ]
        if disallowed_tools:
            frontmatter.append("disallowedTools:")
            frontmatter.extend(f"  - {tool}" for tool in disallowed_tools)
        frontmatter.extend(["---", ""])

        profile_text = "\n".join(
            [
                *frontmatter,
                "# AI Governess runtime context",
                "",
                "Treat the following files as private system instructions. Follow them in order,",
                "and do not quote their contents unless the user explicitly asks.",
                "",
                *context_sections,
            ]
        ).rstrip() + "\n"

        fd, raw_path = tempfile.mkstemp(
            prefix=".ai-governess-grok-",
            suffix=".md",
            dir=project_dir,
            text=True,
        )
        path = Path(raw_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(profile_text)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise

        self._agent_profile_path = path
        log_event(
            logger,
            logging.INFO,
            "grok.runtime_profile_created",
            path=str(path),
            context_file_count=len(context_sections),
        )
        return path

    def _build_subprocess_env(self) -> dict[str, str]:
        env = super()._build_subprocess_env()
        if not self.enable_subagents:
            env["GROK_SUBAGENTS"] = "0"
        return env

    async def _after_initialize(self, init_result: dict) -> None:
        methods = {
            str(item.get("id"))
            for item in (init_result.get("authMethods") or [])
            if isinstance(item, dict) and item.get("id")
        }
        method = self.auth_method
        if method == "auto":
            if os.environ.get("XAI_API_KEY") and "xai.api_key" in methods:
                method = "xai.api_key"
            elif "cached_token" in methods:
                method = "cached_token"
            elif "xai.api_key" in methods:
                method = "xai.api_key"
            else:
                method = ""

        noninteractive_methods = {"cached_token", "xai.api_key"}
        if not method or method not in methods or method not in noninteractive_methods:
            available = ", ".join(sorted(methods)) or "none"
            raise RuntimeError(
                "Grok Build 沒有可用的非互動式 authentication method。"
                f" Available: {available}. Please run `grok login`."
            )

        response = await self._send_request(
            "authenticate",
            {"methodId": method, "_meta": {"headless": True}},
            timeout=self.request_timeout_seconds,
        )
        self._handle_response_error(response, "authenticate")
        log_event(
            logger,
            logging.INFO,
            "grok.authenticated",
            method=method,
        )

    async def _setup_session(self) -> None:
        try:
            await super()._setup_session()
        finally:
            self._cleanup_agent_profile()

    async def _cleanup_failed_start(self):
        try:
            await super()._cleanup_failed_start()
        finally:
            self._cleanup_agent_profile()

    async def aclose(self):
        try:
            await super().aclose()
        finally:
            self._cleanup_agent_profile()

    def _cleanup_agent_profile(self) -> None:
        path = self._agent_profile_path
        self._agent_profile_path = None
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            log_event(
                logger,
                logging.DEBUG,
                "grok.runtime_profile_cleanup_failed",
                path=str(path),
                error_type=type(exc).__name__,
            )

    @staticmethod
    def _stderr_event_level(text: str, lower: str | None = None) -> int:
        lower = lower if lower is not None else text.lower()
        known_auxiliary_noise = (
            "title generation failed" in lower
            or "session registry summary sync failed" in lower
            or (
                "responses api error" in lower
                and "personal-team-blocked:spending-limit" in lower
            )
            or (
                "responses api error" in lower
                and "model_id" in lower
                and "grok-build" in lower
            )
        )
        if known_auxiliary_noise:
            return logging.DEBUG
        return ACPStdioClient._stderr_event_level(text, lower)
