"""Managed Gemini API CLI updates and read-only model discovery; no inference."""
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import tempfile
import threading
import time
from uuid import uuid4
import zipfile

import httpx

from llm.model_catalog import CliCatalog
from utils.gemini_audio import resolve_api_key

MUSIC_MODEL = 'lyria-3.5'
REPOSITORY = 'google-gemini/gemini-api-cli'
RELEASE_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
_LOCK = threading.Lock()


def _check(cancel, deadline):
    if cancel.is_set():
        raise ValueError('Gemini API CLI 操作已取消。')
    if time.monotonic() >= deadline:
        raise ValueError('Gemini API CLI 操作逾時，請稍後重試。')


def runtime_root():
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        raise ValueError('找不到 LOCALAPPDATA，無法定位 Gemini API CLI。')
    return Path(base) / 'AI_Governess' / 'runtimes' / 'gemini-api'


def _receipt():
    pointer = runtime_root() / 'active.json'
    if not pointer.exists():
        return None
    try:
        data = json.loads(pointer.read_text(encoding='utf-8'))
        if (not re.fullmatch(r'v\d+\.\d+\.\d+-(?:x86_64|arm64)-[a-f0-9]{12}', data['directory'])
                or not re.fullmatch(r'[a-f0-9]{64}', data['sha256'])
                or not re.fullmatch(r'v\d+\.\d+\.\d+', data['version'])
                or not re.fullmatch(r'[a-f0-9]{64}', data['archive_sha256'])):
            raise ValueError
        path = runtime_root() / data['directory'] / 'gemini-api.exe'
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != data['sha256']:
            raise ValueError
        return data, path
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('Gemini API CLI 安裝紀錄或檔案無效，請安裝／更新修復。') from None


def resolve_executable(configured=''):
    if configured and str(configured).strip():
        path = Path(str(configured).strip()).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        if not path.is_file() or path.name.lower() != 'gemini-api.exe':
            raise ValueError('請選擇存在的 gemini-api.exe。')
        return str(path.resolve())
    installed = _receipt()
    if installed:
        return str(installed[1])
    resolved = shutil.which('gemini-api.exe')
    standard = Path(os.environ.get('LOCALAPPDATA', '.')) / 'Programs/gemini-api/gemini-api.exe'
    if resolved or standard.is_file():
        return str(Path(resolved or standard).resolve())
    raise ValueError('尚未安裝 Gemini API CLI；請按「安裝／更新 CLI」。')


def _download(url, cancel, deadline, maximum):
    _check(cancel, deadline)
    try:
        timeout = max(.1, min(10, deadline-time.monotonic()))
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream('GET', url, headers={'Accept': 'application/vnd.github+json',
                               'User-Agent': 'AI-Governess-Gemini-CLI-Setup'}) as response:
                if response.status_code != 200:
                    raise ValueError(f'官方下載服務回應 HTTP {response.status_code}，請稍後重試。')
                host = response.url.host
                if (response.url.scheme != 'https' or host not in
                        ('api.github.com', 'github.com', 'release-assets.githubusercontent.com',
                         'objects.githubusercontent.com')):
                    raise ValueError('Gemini API CLI 下載來源不符。')
                chunks, size = [], 0
                for chunk in response.iter_bytes(64*1024):
                    _check(cancel, deadline)
                    size += len(chunk)
                    if size > maximum:
                        raise ValueError('Gemini API CLI 下載超出大小上限。')
                    chunks.append(chunk)
        _check(cancel, deadline)
        return b''.join(chunks)
    except httpx.HTTPError:
        raise ValueError('無法連線至官方 Gemini API CLI 下載服務。') from None


def install_cli(*, cancel, deadline, progress=None):
    """Activate only a digest-verified official Windows release; retain old files."""
    machine = platform.machine().upper()
    architecture = {'AMD64': 'x86_64', 'X86_64': 'x86_64', 'ARM64': 'arm64'}.get(machine)
    if os.name != 'nt' or not architecture:
        raise ValueError('Gemini API CLI 安裝目前支援 Windows x64／ARM64。')
    _check(cancel, deadline)
    while not _LOCK.acquire(timeout=.1):
        _check(cancel, deadline)
    try:
        if progress:
            progress('查詢 Google 官方 Gemini API CLI 最新版本…')
        metadata = _download(RELEASE_URL, cancel, deadline, 2_000_000)
        try:
            release = json.loads(metadata)
            version = release['tag_name']
            if not re.fullmatch(r'v\d+\.\d+\.\d+', version) or release.get('prerelease') or release.get('draft'):
                raise ValueError
            name = f'gemini-api_Windows_{architecture}.zip'
            matches = [a for a in release['assets'] if a.get('name') == name]
            if len(matches) != 1:
                raise ValueError
            asset = matches[0]
            expected_url = f'https://github.com/{REPOSITORY}/releases/download/{version}/{name}'
            digest = asset.get('digest', '')
            if asset.get('browser_download_url') != expected_url or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ValueError('官方 Gemini API CLI release 格式無效，既有安裝保持不變。') from None
        try:
            current = _receipt()
        except ValueError:
            current = None  # A successful verified install can repair the pointer.
        if current:
            previous = current[0]
            if tuple(map(int, version[1:].split('.'))) < tuple(map(int, previous['version'][1:].split('.'))):
                raise ValueError('官方版本較已安裝版本舊，保留既有版本。')
            if previous['version'] == version and previous['archive_sha256'] == digest[7:]:
                _check(cancel, deadline)
                return {'executable': str(current[1]), 'version': version, 'updated': False}
        if progress:
            progress(f'下載並驗證 Gemini API CLI {version}…')
        archive = _download(expected_url, cancel, deadline, 64*1024*1024)
        if hashlib.sha256(archive).hexdigest() != digest[7:]:
            raise ValueError('Gemini API CLI SHA256 不符，未啟用下載內容。')
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                files = [f for f in bundle.infolist() if f.filename == 'gemini-api.exe']
                if len(files) != 1 or not 1 <= files[0].file_size <= 64*1024*1024:
                    raise ValueError
                binary = bundle.read(files[0])  # Never extract arbitrary archive paths.
                if not binary.startswith(b'MZ'):
                    raise ValueError
        except (ValueError, zipfile.BadZipFile, RuntimeError):
            raise ValueError('Gemini API CLI archive 沒有有效的 Windows executable。') from None
        _check(cancel, deadline)
        root = runtime_root()
        root.mkdir(parents=True, exist_ok=True)
        directory = f'{version}-{architecture}-{uuid4().hex[:12]}'
        target = root / directory
        with tempfile.TemporaryDirectory(prefix='.install-', dir=root) as staging:
            temporary = Path(staging)
            (temporary / 'gemini-api.exe').write_bytes(binary)
            receipt = {'directory': directory, 'version': version, 'sha256': hashlib.sha256(binary).hexdigest(),
                       'archive_sha256': digest[7:]}
            pointer = temporary / 'active.json'
            pointer.write_text(json.dumps(receipt)+'\n', encoding='utf-8')
            _check(cancel, deadline)
            target.mkdir()
            os.replace(temporary / 'gemini-api.exe', target / 'gemini-api.exe')
            _check(cancel, deadline)
            os.replace(pointer, root / 'active.json')
        return {'executable': str(target / 'gemini-api.exe'), 'version': version, 'updated': True}
    finally:
        _LOCK.release()


def query_models(settings, *, cancel, deadline, progress=None):
    """Fetch bounded model metadata pages through the actual CLI, without a prompt."""
    _check(cancel, deadline)
    credential = settings.get('gemini', {})
    key = resolve_api_key(credential.get('api_key', ''), credential.get('api_key_env', 'GEMINI_API_KEY'))
    executable = resolve_executable(settings.get('gemini_api_cli', {}).get('executable', ''))
    env = dict(os.environ, GEMINI_API_KEY=key)
    for name in ('GOOGLE_API_KEY', 'GEMINI_ACCESS_TOKEN', 'GEMINI_DEBUG', 'DEBUG'):
        env.pop(name, None)
    version_output = CliCatalog._run([executable, '--version'], cancel, deadline, env=env)
    match = re.search(r'gemini-api\s+(\d+\.\d+\.\d+)', version_output)
    version = match[1] if match else '未知版本'
    names, seen, token = [], set(), None
    for page in range(10):
        _check(cancel, deadline)
        if progress:
            progress(f'Gemini API CLI {version}：查詢模型第 {page+1} 頁…')
        command = [executable, '--no-interactive', 'models', 'list', '--output-format', 'json',
                   '--page-size', '1000', '--timeout', '15s']
        if token:
            command += ['--page-token', token]
        raw = CliCatalog._run(command, cancel, deadline, env=env)
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get('models'), list):
                raise ValueError
            for model in data['models']:
                identifier = model.get('name') or model.get('id')
                if not isinstance(identifier, str):
                    raise ValueError
                identifier = identifier.removeprefix('models/')
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,199}', identifier):
                    raise ValueError
                if identifier not in names:
                    names.append(identifier)
                if len(names) > 5000:
                    raise ValueError
            token = data.get('nextPageToken') or data.get('next_page_token')
            if not token:
                if not names:
                    raise ValueError
                return {'models': tuple(names), 'version': version, 'executable': executable}
            if not isinstance(token, str) or len(token) > 4096 or token in seen:
                raise ValueError
            seen.add(token)
        except (ValueError, TypeError, AttributeError):
            raise ValueError('Gemini API CLI 回傳的模型清單格式無效。') from None
    raise ValueError('Gemini API CLI 模型分頁超出上限，未使用不完整清單。')
