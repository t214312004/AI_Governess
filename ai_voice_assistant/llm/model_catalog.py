"""Query installed CLI capabilities without sending a user prompt."""
import asyncio
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time

from core.session_settings import BACKENDS


@dataclass(frozen=True)
class ModelInfo:
    id: str
    efforts: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip() or len(self.id) > 200:
            raise ValueError('模型識別字無效')
        if not isinstance(self.efforts, tuple) or any(not isinstance(e, str) or not e for e in self.efforts):
            raise ValueError('Effort 清單無效')


class CliCatalog:
    def __init__(self, settings):
        self.settings = settings

    def query(self, backend, update, *, cancel: threading.Event, timeout=180, progress=None, authenticate=False):
        if backend not in BACKENDS:
            raise ValueError('不支援的 Backend')
        deadline = time.monotonic() + timeout
        settings = deepcopy(self.settings())
        if backend == 'antigravity_cli':
            if update:
                from llm.antigravity_runtime import install_runtime
                installed = install_runtime(cancel=cancel, deadline=deadline, progress=progress, update=True)
                # An explicit older executable must not make the post-update
                # catalog silently query the old server again.
                settings['llm'][backend]['executable'] = installed
            self._executable(backend, settings)
        else:
            executable = self._executable(backend, settings)
        if update and backend != 'antigravity_cli':
            if progress: progress('正在更新 CLI；可按「取消查詢」停止。')
            updates = {'codex_cli': ['update'], 'claude_code': ['update'],
                       'opencode_cli': ['upgrade'], 'grok_cli': ['update']}
            self._run([executable, *updates[backend]], cancel, deadline)
        if progress: progress('正在查詢模型與推理選項；可按「取消查詢」停止。')
        if backend == 'claude_code':
            request = {'type': 'control_request', 'request_id': 'startup-models',
                       'request': {'subtype': 'initialize', 'hooks': None}}
            output = self._run([executable, '-p', '--input-format', 'stream-json',
                '--output-format', 'stream-json', '--verbose'], cancel, deadline, request=request)
            payload = {}
            for line in output.splitlines():
                try:
                    response = json.loads(line)
                except ValueError:
                    continue
                if isinstance(response, dict) and response.get('type') == 'control_response':
                    payload = response.get('response', {}).get('response', {})
                    break
            models = tuple(ModelInfo(m.get('value') or m.get('id'),
                tuple(m.get('supportedEffortLevels', ()))) for m in payload.get('models', ()))
        else:
            models = asyncio.run(self._query_protocol(backend, settings, cancel, deadline, authenticate=authenticate))
        if not models:
            raise ValueError('CLI 沒有回傳模型清單，請確認已登入並可連線')
        return models

    @staticmethod
    def _executable(backend, settings):
        if backend == 'antigravity_cli':
            from llm.antigravity_runtime import resolve_runtime_executable
            resolved = resolve_runtime_executable(settings['llm'][backend].get('executable', ''))
            if resolved:
                return resolved
            raise ValueError('尚未安裝官方 Antigravity ACP；請按「安裝／更新官方 ACP 並查詢模型」。')
        names = {'codex_cli': ('codex.exe', 'codex.cmd', 'codex'),
                 'claude_code': ('claude.exe', 'claude.cmd', 'claude'),
                 'opencode_cli': ('opencode.exe', 'opencode.cmd', 'opencode'),
                 'grok_cli': ('grok.exe', 'grok.cmd', 'grok')}
        if backend == 'grok_cli':
            configured = settings['llm'][backend].get('executable', '')
            for path in (configured, str(Path.home() / '.grok/bin/grok.exe')):
                if path and Path(path).is_file():
                    return str(Path(path).resolve())
        for name in names[backend]:
            resolved = shutil.which(name)
            if resolved:
                return resolved
        raise ValueError(f'找不到 {backend} CLI，請先安裝並登入')

    @staticmethod
    def _run(command, cancel, deadline, request=None, *, env=None):
        """Bound waits and output; own only this subprocess and its descendants."""
        if cancel.is_set():
            raise ValueError('查詢已取消')
        job = None
        process = None
        if os.name == 'nt' and Path(command[0]).suffix.lower() in ('.cmd', '.bat'):
            # cmd batch wrappers accept only these fixed CLI commands and paths.
            if any(re.search(r'[&|<>%^!\r\n]', part) for part in command):
                raise ValueError('CLI wrapper 路徑包含不支援的字元')
            command = [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/s', '/c',
                       subprocess.list2cmdline(command)]
        with tempfile.TemporaryDirectory(prefix='cli-query-') as work, open(Path(work) / 'output.txt', 'w+b') as output:
            try:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=output,
                    stderr=output, env=env,
                    creationflags=(subprocess.CREATE_NO_WINDOW | 4) if os.name == 'nt' else 0)
                if os.name == 'nt':
                    from ui.windows_job import WindowsJob
                    from llm.process_owner import resume_owned_process
                    job = WindowsJob()
                    resume_owned_process(job, process.pid)
                if request is not None:
                    process.stdin.write((json.dumps(request) + '\n').encode())
                    process.stdin.flush()
                while True:
                    if cancel.is_set():
                        raise ValueError('查詢已取消')
                    if time.monotonic() >= deadline:
                        raise ValueError('CLI 更新或查詢逾時')
                    if os.fstat(output.fileno()).st_size > 2_000_000:
                        raise ValueError('CLI 回傳內容超出上限')
                    if request is not None:
                        # A separate reader avoids moving the child's shared file offset.
                        with open(output.name, 'rb') as reader:
                            content = reader.read(2_000_001).decode('utf-8', errors='replace')
                        for line in content.splitlines():
                            try:
                                response = json.loads(line)
                            except ValueError:
                                continue
                            if isinstance(response, dict) and response.get('type') == 'control_response':
                                return content
                    if process.poll() is not None:
                        output.seek(0)
                        content = output.read(2_000_001).decode('utf-8', errors='replace')
                        if process.returncode:
                            raise ValueError(f'CLI 執行失敗（exit {process.returncode}），請確認安裝與登入狀態')
                        return re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', content)
                    cancel.wait(.1)
            finally:
                if job is not None:
                    job.close()
                if process is not None:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=5)
                    process.stdin.close()

    async def _query_protocol(self, backend, settings, cancel, deadline, *, authenticate=False):
        from llm.client_factory import create_llm_client
        with tempfile.TemporaryDirectory(prefix='ai-governess-catalog-') as workspace:
            # Catalog sessions never load the household's private memory.
            for name in ('AGENTS.md', 'MEMORY.md'):
                Path(workspace, name).write_text('', encoding='utf-8')
            options = dict(settings['llm'][backend], project_dir=workspace, model='',
                           reasoning_effort='', mode='', load_private_context=False,
                           required_context_files=['AGENTS.md'], instruction_files=['MEMORY.md'])
            if backend == 'antigravity_cli':
                options.update(effort='', mode='yolo', mcp_servers=[],
                               required_context_files=['AGENTS.md', 'MEMORY.md'])
            client = create_llm_client(backend, **options)
            if backend in ('codex_cli', 'antigravity_cli'):
                client._catalog_only = True
            async def fetch():
                if authenticate:
                    if backend != 'antigravity_cli':
                        raise ValueError('此登入操作僅適用於 Antigravity ACP。')
                    await client.authenticate_personal(timeout_seconds=min(300, max(1, deadline-time.monotonic())))
                if backend == 'codex_cli':
                    await client._start_server()
                else:
                    await client.ensure_ready()
                if backend == 'codex_cli':
                    results, cursor, seen = [], None, set()
                    while True:
                        params = {'limit': 100, 'includeHidden': False}
                        if cursor:
                            params['cursor'] = cursor
                        response = await client._send_request('model/list', params)
                        client._raise_for_error(response, '查詢模型失敗')
                        page = response.get('result') or {}
                        for model in page.get('data', ()):
                            results.append(ModelInfo(model.get('model') or model['id'],
                                tuple(e['reasoningEffort'] for e in model.get('supportedReasoningEfforts', ()))))
                        cursor = page.get('nextCursor')
                        if not cursor:
                            return tuple(results)
                        if cursor in seen or len(results) > 500:
                            raise ValueError('模型分頁格式無效')
                        seen.add(cursor)
                options = client._session_config_options or []
                model_option = client._find_config_option(options, 'model')
                models = client._config_option_values(model_option) if model_option else [
                    m['modelId'] for m in getattr(client, '_available_models', ())]
                results = []
                for model in models:
                    if model_option:
                        # A model change may advertise different thought levels.
                        current = client._session_config_options if client._session_config_options is not None else options
                        await client._set_config_option(current, 'model', model)
                    current = client._session_config_options if client._session_config_options is not None else options
                    effort_option = next((o for o in current if isinstance(o, dict) and
                        (o.get('category') == 'thought_level' or o.get('id') in ('reasoning_effort', 'effort', 'thinking_level'))), None)
                    efforts = tuple(client._config_option_values(effort_option)) if effort_option else ()
                    results.append(ModelInfo(model, efforts))
                return tuple(results)
            task = asyncio.create_task(fetch())
            try:
                while not task.done():
                    if cancel.is_set() or time.monotonic() >= deadline:
                        task.cancel()
                        raise ValueError('查詢已取消或逾時')
                    await asyncio.sleep(.1)
                return await task
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await client.aclose()
