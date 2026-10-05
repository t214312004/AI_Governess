"""Query installed CLI capabilities without sending a user prompt."""
import asyncio
import ctypes
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


def advertised_choices(help_text, flag):
    """Extract only CLI-advertised choices; never invent capability values."""
    match = re.search(re.escape(flag) + r'[^\n]*?(?:\(([^)]+)\)|\[choices:\s*([^]]+)\])', help_text)
    if not match:
        return ()
    return tuple(x.strip(' \"\'') for x in re.split(r'[|,]', match.group(1) or match.group(2)) if x.strip())


def antigravity_models(output, efforts):
    models = []
    for line in output.splitlines():
        if '\t' not in line:
            continue
        identifier, title = line.split('\t', 1)
        identifier = identifier.strip()
        if not identifier:
            continue
        # Concrete effort variants cannot be combined with another --effort.
        pinned = tuple(e for e in efforts if identifier.endswith('-' + e)
                       or re.search(r'\(' + re.escape(e) + r'\)\s*$', title, re.I))
        models.append(ModelInfo(identifier, pinned))
    return tuple(models)


class CliCatalog:
    def __init__(self, settings):
        self.settings = settings

    def query(self, backend, update, *, cancel: threading.Event, timeout=180):
        if backend not in BACKENDS:
            raise ValueError('不支援的 Backend')
        deadline = time.monotonic() + timeout
        settings = self.settings()
        executable = self._executable(backend, settings)
        if update:
            updates = {'codex_cli': ['update'], 'claude_code': ['update'],
                       'opencode_cli': ['upgrade'], 'grok_cli': ['update'],
                       'antigravity_cli': ['update']}
            self._run([executable, *updates[backend]], cancel, deadline)
        if backend == 'antigravity_cli':
            help_text = self._run([executable, '--help'], cancel, deadline)
            efforts = advertised_choices(help_text, '--effort')
            output = self._run([executable, 'models'], cancel, deadline)
            models = antigravity_models(output, efforts)
        elif backend == 'claude_code':
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
            models = asyncio.run(self._query_protocol(backend, settings, cancel, deadline))
        if not models:
            raise ValueError('CLI 沒有回傳模型清單，請確認已登入並可連線')
        return models

    @staticmethod
    def _executable(backend, settings):
        names = {'codex_cli': ('codex.exe', 'codex.cmd', 'codex'),
                 'claude_code': ('claude.exe', 'claude.cmd', 'claude'),
                 'opencode_cli': ('opencode.exe', 'opencode.cmd', 'opencode'),
                 'grok_cli': ('grok.exe', 'grok.cmd', 'grok'),
                 'antigravity_cli': ('agy.exe', 'agy')}
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
    def _run(command, cancel, deadline, request=None):
        """Bound waits and output; own only this subprocess and its descendants."""
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
                    stderr=output, creationflags=(subprocess.CREATE_NO_WINDOW | 4) if os.name == 'nt' else 0)
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

    async def _query_protocol(self, backend, settings, cancel, deadline):
        from llm.client_factory import create_llm_client
        with tempfile.TemporaryDirectory(prefix='ai-governess-catalog-') as workspace:
            # Catalog sessions never load the household's private memory.
            for name in ('AGENTS.md', 'MEMORY.md'):
                Path(workspace, name).write_text('', encoding='utf-8')
            options = dict(settings['llm'][backend], project_dir=workspace, model='',
                           reasoning_effort='', mode='', load_private_context=False,
                           required_context_files=['AGENTS.md'], instruction_files=['MEMORY.md'])
            client = create_llm_client(backend, **options)
            if backend == 'codex_cli':
                client._catalog_only = True
            async def fetch():
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
                        (o.get('category') == 'thought_level' or o.get('id') in ('reasoning_effort', 'effort'))), None)
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
