import json
import logging
import os
import shutil
from pathlib import Path

from .acp_stdio_client import ACPStdioClient
from utils.logger import get_logger, log_event

logger = get_logger(__name__)

APP_DIR = Path(__file__).resolve().parents[1]
AGENT_WORKSPACE_TEMPLATE_DIR = APP_DIR / "agent_workspace_template"


def _resolve_project_dir(project_dir: str) -> Path:
    raw = Path(project_dir or "./agent_workspace")
    if raw.is_absolute():
        return raw.resolve()
    return (APP_DIR / raw).resolve()


def _as_opencode_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


class OpenCodeCLIClient(ACPStdioClient):
    """
    OpenCode ACP backend.

    OpenCode uses ACP v1 and receives model/mode through
    session/set_config_option, not through CLI flags.
    """

    unavailable_message = (
        "OpenCode CLI backend 尚未就緒，請確認 opencode 已安裝、已登入，"
        "且 agent_workspace 的 AGENTS.md / MEMORY.md 可讀取。"
    )

    def __init__(
        self,
        project_dir: str = "./agent_workspace",
        session_id: str | None = None,
        model: str | None = None,
        mode: str | None = None,
        permission_mode: str = "yolo",
        auto_approve: bool = True,
        use_runtime_config_content: bool = True,
        enable_web_search: bool = False,
        required_context_files: list[str] | None = None,
        instruction_files: list[str] | None = None,
        shell: str | None = None,
        env_overrides: dict[str, str] | None = None,
    ):
        resolved_project_dir = _resolve_project_dir(project_dir)
        self.use_runtime_config_content = bool(use_runtime_config_content)
        self.enable_web_search = bool(enable_web_search)
        self._resolved_instruction_paths: list[Path] = []

        super().__init__(
            backend_name="opencode",
            project_dir=str(resolved_project_dir),
            executable_names=["opencode.cmd", "opencode.exe", "opencode"],
            command_args=["acp", "--cwd", str(resolved_project_dir)],
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
            mode=mode or None,
            permission_mode=permission_mode or "yolo",
            auto_approve=auto_approve,
            required_context_files=required_context_files or ["AGENTS.md"],
            instruction_files=instruction_files or ["MEMORY.md"],
            shell=shell or None,
            env_overrides=env_overrides or {},
        )
        self.session_id = session_id

    def _before_start(self) -> None:
        self._bootstrap_private_workspace_files()
        self._check_context_files()

    def _bootstrap_private_workspace_files(self) -> None:
        project_dir = Path(self.project_dir)
        project_dir.mkdir(parents=True, exist_ok=True)

        if not AGENT_WORKSPACE_TEMPLATE_DIR.exists():
            log_event(
                logger,
                logging.WARNING,
                "opencode.context_template_missing",
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
            if destination.exists() or not source.exists() or not source.is_file():
                continue

            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            log_event(
                logger,
                logging.INFO,
                "opencode.context_bootstrap_file",
                path=str(destination),
                template=str(source),
            )

    def _check_context_files(self) -> None:
        project_dir = Path(self.project_dir)
        resolved_instruction_paths: list[Path] = []

        for rel_path in self.required_context_files:
            path = project_dir / str(rel_path)
            exists = path.exists()
            log_event(
                logger,
                logging.INFO if exists else logging.WARNING,
                "opencode.required_context_file",
                path=str(path),
                exists=exists,
                source="project_rules",
            )

        for rel_path in self.instruction_files:
            path = project_dir / str(rel_path)
            exists = path.exists()
            log_event(
                logger,
                logging.INFO if exists else logging.WARNING,
                "opencode.instruction_file",
                path=str(path),
                exists=exists,
                source="runtime_config",
            )
            if exists:
                resolved_instruction_paths.append(path.resolve())

        self._resolved_instruction_paths = resolved_instruction_paths

    def _build_subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()

        if self.use_runtime_config_content:
            config_content = {
                "$schema": "https://opencode.ai/config.json",
            }
            if self.permission_mode == "yolo":
                config_content["permission"] = "allow"
            elif self.permission_mode in {"allow", "ask", "deny"}:
                config_content["permission"] = self.permission_mode

            if self._resolved_instruction_paths:
                config_content["instructions"] = [
                    _as_opencode_path(path) for path in self._resolved_instruction_paths
                ]

            if self.shell:
                config_content["shell"] = self.shell

            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(
                config_content,
                ensure_ascii=False,
                separators=(",", ":"),
            )

        if self.enable_web_search:
            env["OPENCODE_ENABLE_EXA"] = "1"

        env.update(self.env_overrides)
        return env
