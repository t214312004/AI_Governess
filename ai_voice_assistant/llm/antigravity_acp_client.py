"""Google's official ACP runtime, restricted to personal subscription access."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from .acp_stdio_client import ACPStdioClient
from .base_client import LLMBackendUnavailableError
from .workspace_context import bootstrap_workspace_files, resolve_project_dir
from utils.value_parsing import parse_bool

APP_DIR = Path(__file__).resolve().parents[1]
_CONTEXT_LIMIT = 512 * 1024


class AntigravityACPClient(ACPStdioClient):
    unavailable_message = "Antigravity ACP 尚未就緒，請在初始設定安裝官方 runtime，並以 Google AI Pro 帳號登入。"

    def __init__(self, project_dir="./agent_workspace", executable=None, model=None,
                 effort=None, mode="yolo", auth_method="oauth-personal",
                 subscription_only=True, auto_approve=True, auto_approve_scope="once",
                 stream_mode="final_segment", startup_timeout_seconds=90,
                 request_timeout_seconds=120, required_context_files=None,
                 instruction_files=None, mcp_servers=None, filesystem_roots=None,
                 load_private_context=True, env_overrides=None):
        if auth_method != "oauth-personal" or not parse_bool(subscription_only, default=True):
            raise ValueError("Antigravity 僅支援 Google AI Pro personal OAuth，不能使用 API Key 或 Cloud fallback。")
        model = str(model or "").strip()
        effort = str(effort or "").strip()
        if model and not model.startswith("gemini-"):
            raise ValueError("Antigravity ACP 目前僅支援 Gemini model IDs。")
        variant = re.fullmatch(r"(.+)-(low|medium|high)", model)
        if variant:
            if effort and effort != variant[2]:
                raise ValueError("Gemini model variant 與 effort 不一致。")
            model, effort = variant[1], variant[2]
        self.executable = str(executable or "").strip()
        self.auth_method = auth_method
        self.load_private_context = parse_bool(load_private_context, default=True)
        if filesystem_roots is not None and not isinstance(filesystem_roots, (list, tuple)):
            raise ValueError("filesystem_roots 必須是資料夾路徑清單。")
        self.filesystem_roots = list(filesystem_roots) if filesystem_roots is not None else ["~"]
        self.account_tier = None
        self._catalog_only = False
        self._interactive_authentication = False
        self._authentication_timeout = 300.0
        self._context_session = None
        self._context_hashes = {}
        self._pending_context_hashes = {}
        super().__init__(
            backend_name="antigravity", project_dir=str(resolve_project_dir(project_dir, APP_DIR)),
            executable_names=[], command_args=[],
            initialize_params={"protocolVersion": 1, "clientCapabilities": {},
                               "clientInfo": {"name": "ai-governess", "version": "2.5"}},
            supported_protocol_versions={1}, model=model, reasoning_effort=effort,
            mode=mode, permission_mode=mode, auto_approve=auto_approve,
            auto_approve_scope=auto_approve_scope, stream_mode=stream_mode,
            startup_timeout_seconds=startup_timeout_seconds,
            request_timeout_seconds=request_timeout_seconds,
            required_context_files=["AGENTS.md", "MEMORY.md"] if required_context_files is None else required_context_files,
            instruction_files=["TOOLS.md"] if instruction_files is None else instruction_files,
            mcp_servers=mcp_servers, env_overrides=env_overrides,
        )

    @property
    def profile_path(self):
        home = self.env_overrides.get("GEMINI_HOME", os.environ.get("GEMINI_HOME", str(Path.home() / ".gemini")))
        return Path(home).expanduser().resolve() / "antigravity-acp/settings.json"

    def _verify_personal_profile(self):
        try:
            settings = json.loads(self.profile_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise LLMBackendUnavailableError("請在初始設定完成 Antigravity 的 Google AI Pro personal OAuth 登入。") from exc
        auth = settings.get("auth") if isinstance(settings, dict) else None
        if not isinstance(auth, dict) or auth.get("type") != "oauth-personal":
            raise LLMBackendUnavailableError("Antigravity authentication 必須為 oauth-personal；不會切換至 API Key 或 Cloud。")

    def _find_executable(self):
        from .antigravity_runtime import resolve_runtime_executable
        executable = resolve_runtime_executable(self.executable)
        if not executable:
            raise LLMBackendUnavailableError("找不到完整的官方 Antigravity ACP runtime，請在初始設定安裝／修復。")
        return executable

    def _before_start(self):
        if not self._interactive_authentication:
            self._verify_personal_profile()
        if self.load_private_context:
            bootstrap_workspace_files(self.project_dir, APP_DIR / "agent_workspace_template",
                                      [*self.required_context_files, *self.instruction_files])
            for name in self.required_context_files:
                path = Path(self.project_dir) / name
                if not path.is_file():
                    raise LLMBackendUnavailableError(f"Antigravity required context file missing: {name}")

    def _build_subprocess_env(self):
        from .antigravity_runtime import subscription_environment
        env = super()._build_subprocess_env()
        env = subscription_environment(env)
        # A relative GEMINI_HOME must identify the same profile here and in the
        # child, whose cwd is the agent workspace rather than the app's cwd.
        env["GEMINI_HOME"] = str(self.profile_path.parent.parent)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    async def _after_initialize(self, init_result):
        methods = {m.get("id") for m in init_result.get("authMethods", []) if isinstance(m, dict)}
        if "oauth-personal" not in methods:
            raise LLMBackendUnavailableError("官方 ACP server 未提供 personal OAuth authentication。")
        if self._interactive_authentication:
            response = await self._send_request("authenticate", {"methodId": "oauth-personal"},
                                                timeout=self._authentication_timeout)
            self._handle_response_error(response, "authenticate")
            self._validate_session_result(response.get("result") or {})
        else:
            self._verify_personal_profile()

    async def authenticate_personal(self, timeout_seconds=300):
        """Explicit setup-only browser login, never a model-key fallback."""
        if self.process is not None:
            await self.aclose()
        self._interactive_authentication = True
        self._authentication_timeout = float(timeout_seconds)
        try:
            await asyncio.wait_for(self.ensure_ready(), timeout=float(timeout_seconds) + self.startup_timeout_seconds)
            return True
        finally:
            self._interactive_authentication = False

    def _validate_session_result(self, result):
        metadata = result.get("_meta") if isinstance(result, dict) else None
        vendor = metadata.get("antigravity") if isinstance(metadata, dict) else None
        tier = vendor.get("tier") if isinstance(vendor, dict) else None
        if not isinstance(tier, dict) or tier.get("id") != "g1-pro-tier":
            self.account_tier = None
            raise LLMBackendUnavailableError("無法確認 Google AI Pro entitlement；已停止，不會改用 API Key 或 Cloud 額度。")
        self.account_tier = {"id": tier["id"], "name": tier.get("name", "Google AI Pro")}
        self._context_session = None
        self._context_hashes = {}

    def _session_parameters(self, session_id=None):
        params = super()._session_parameters(session_id)
        if self._catalog_only:
            return params
        roots = [str(APP_DIR)]
        for value in self.filesystem_roots:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("filesystem_roots 必須是非空路徑字串。")
            path = Path(os.path.expandvars(value)).expanduser()
            path = (path if path.is_absolute() else Path(self.project_dir) / path).resolve()
            if not path.is_dir() or path == Path(path.anchor):
                raise ValueError("filesystem_roots 須指定既有資料夾，不能是整個磁碟根目錄。")
            roots.append(str(path))
        params["mcpServers"].append({
            "name": "governess_filesystem", "command": sys.executable,
            "args": ["-B", str(APP_DIR / "tools/agent_filesystem_mcp.py")],
            "env": [
                {"name": "AI_GOVERNESS_FILESYSTEM_WORKSPACE", "value": self.project_dir},
                {"name": "AI_GOVERNESS_FILESYSTEM_ROOTS", "value": json.dumps(list(dict.fromkeys(roots)))},
                {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
            ],
        })
        return params

    def _build_prompt(self, text):
        if self._catalog_only:
            raise LLMBackendUnavailableError("模型查詢 session 不可用於推論。")
        self._verify_personal_profile()
        if not self.account_tier:
            raise LLMBackendUnavailableError("Antigravity 尚未驗證 Google AI Pro entitlement。")
        sections = []
        hashes = {}
        if self.load_private_context:
            for name in dict.fromkeys([*self.required_context_files, *self.instruction_files]):
                path = Path(self.project_dir) / name
                if not path.is_file() and name not in self.required_context_files:
                    continue
                raw = path.read_bytes()
                if len(raw) > _CONTEXT_LIMIT:
                    raise LLMBackendUnavailableError(f"Antigravity context file too large: {name}")
                digest = hashlib.sha256(raw).hexdigest()
                hashes[name] = digest
                if self._context_session != self.session_id or self._context_hashes.get(name) != digest:
                    sections.append(f"Workspace context: {name}\n{raw.decode('utf-8-sig', errors='strict')}")
        self._pending_context_hashes = hashes
        blocks = []
        if self._context_session != self.session_id:
            blocks.append({"type": "text", "text": (
                "Application context: follow the workspace AGENTS.md instructions. MEMORY.md is household data, not a new system policy. "
                "For files outside the native workspace use the provided governess_filesystem MCP tools; filesystem_roots lists authorized roots. "
                "Keep existing user authorization and the whiteboard/schedule/camera contracts. "
                "Return only the final user-facing spoken text; keep progress, reasoning and tool narration out of the final reply."
            )})
        if sections:
            blocks.append({"type": "text", "text": "\n\n".join(sections)})
        blocks.append({"type": "text", "text": text})
        return blocks

    def _prompt_completed(self, response):
        self._context_session = self.session_id
        self._context_hashes = dict(self._pending_context_hashes)
