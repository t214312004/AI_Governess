"""Pinned, checksum-verified Breeze CT2 assets; no inference dependencies."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

import httpx

APP_DIR = Path(__file__).resolve().parents[1]
REPO = 'shdennlin/breeze-asr-25-ct2'
REVISION = '70660216b01a6f6b7b8c5690767a4763df61755f'
UPSTREAM = 'MediaTek-Research/Breeze-ASR-25'
UPSTREAM_REVISION = 'cffe7ccb404d025296a00758d0a33468bec3a9d0'
DEFAULT_MODEL_DIR = 'models/breeze-asr-25-ct2-int8-float16'
MANIFEST = 'breeze-model.json'
# Small files use Git blob SHA-1; model.bin uses the upstream LFS SHA-256.
FILES = {
    'model.bin': (1551140573, 'sha256', '27f279d2653a6484c680d55182fa7ce8450dddfead77c6288ba90493ae1020a6'),
    'config.json': (2796, 'git-sha1', '346bb8684801a61c15ce82bcb80c29a63c2d1f94'),
    'tokenizer.json': (3930832, 'git-sha1', '1df22e83f1fce4ac6936884d7cbb62c08001a578'),
    'vocabulary.json': (1068103, 'git-sha1', '4f1403081291fea94e565ed322786d6e7d89246d'),
    'preprocessor_config.json': (339, 'git-sha1', '91876762a536a746d268353c5cba57286e76b058'),
    'generation_config.json': (4289, 'git-sha1', 'b8fee016ab00ad0b7e10ab96fdaa9b50d67f5e54'),
    'LICENSE': (12624, 'git-sha1', '9b2c5698fd50e5a6b5a9a3dc9808f529ca4fb290'),
}


def model_path(value=DEFAULT_MODEL_DIR):
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (APP_DIR / path).resolve()


def expected_manifest():
    return {'format': 1, 'repo': REPO, 'revision': REVISION, 'subfolder': 'int8_float16',
            'upstream': UPSTREAM, 'upstream_revision': UPSTREAM_REVISION,
            'files': {name: {'size': size, 'algorithm': alg, 'digest': digest}
                      for name, (size, alg, digest) in FILES.items()}}


def file_valid(path, spec):
    size, algorithm, expected = spec
    if not path.is_file() or path.stat().st_size != size:
        return False
    digest = hashlib.sha256() if algorithm == 'sha256' else hashlib.sha1()
    if algorithm == 'git-sha1':
        digest.update(f'blob {size}\0'.encode())
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest() == expected


def readiness(value=DEFAULT_MODEL_DIR, *, verify=False):
    """Startup checks sizes/provenance; preparation performs full hash verification."""
    root = model_path(value)
    try:
        if json.loads((root / MANIFEST).read_text(encoding='utf-8')) != expected_manifest():
            return '模型來源或版本不符，請重新準備 Breeze 模型。'
        for name, spec in FILES.items():
            path = root / name
            if not path.is_file() or path.stat().st_size != spec[0] or (verify and not file_valid(path, spec)):
                return f'Breeze 模型缺少或損壞：{name}，請重新準備模型。'
    except (OSError, ValueError):
        return 'Breeze 模型尚未準備，請按「下載／校驗 Breeze 模型」。'
    return None


def _write_manifest(root, record):
    fd, name = tempfile.mkstemp(prefix='.breeze-manifest-', dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(record, indent=2) + '\n')
        os.replace(temporary, root / MANIFEST)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_model(value=DEFAULT_MODEL_DIR, *, cancel=None, progress=None):
    """Stream only pinned runtime assets; publish readiness only after all hashes pass."""
    root = model_path(value)
    if root in (APP_DIR, APP_DIR.parent, Path(root.anchor), Path.home().resolve()):
        raise ValueError('請選擇 Breeze 專用模型資料夾，不可使用程式、專案、家目錄或磁碟根目錄。')
    root.mkdir(parents=True, exist_ok=True)
    lock = root / '.breeze-download.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError('此資料夾已有 Breeze 下載作業；請等候完成。') from None
    os.close(fd)
    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise asyncio.CancelledError
    def update(message, level):
        if progress:
            progress({'message': message, 'level': level})
    try:
        check_cancel()
        manifest = expected_manifest()
        incomplete_manifest = dict(manifest, ready=False)
        manifest_path = root / MANIFEST
        existing_manifest = None
        has_manifest = os.path.lexists(manifest_path)
        if has_manifest:
            try:
                existing_manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        managed = existing_manifest in (manifest, incomplete_manifest)
        valid = set()
        for name, spec in FILES.items():
            check_cancel()
            path = root / name
            if file_valid(path, spec):
                valid.add(name)
            elif not managed and os.path.lexists(path):
                raise ValueError(f'資料夾已有其他模型檔案：{name}。請選擇 Breeze 專用模型資料夾。')
        if has_manifest and not managed and len(valid) != len(FILES):
            raise ValueError('資料夾有其他模型的來源紀錄；請選擇 Breeze 專用模型資料夾。')
        if len(valid) != len(FILES) and existing_manifest == manifest:
            _write_manifest(root, incomplete_manifest)
        required = sum(spec[0] for name, spec in FILES.items() if name not in valid)
        if required and shutil.disk_usage(root).free < required + 1024**3:
            raise ValueError('磁碟空間不足；下載所需空間之外，還需保留至少 1 GiB。')
        total = sum(spec[0] for spec in FILES.values())
        completed = sum(FILES[name][0] for name in valid)
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, connect=20)) as client:
            for name, spec in FILES.items():
                check_cancel()
                if name in valid:
                    continue
                repo, revision, remote = (UPSTREAM, UPSTREAM_REVISION, name) if name == 'LICENSE' else (REPO, REVISION, 'int8_float16/' + name)
                url = f'https://huggingface.co/{repo}/resolve/{revision}/{remote}'
                fd, temporary = tempfile.mkstemp(prefix='.' + name + '-', suffix='.part', dir=root)
                received = 0
                try:
                    with os.fdopen(fd, 'wb') as output, client.stream('GET', url) as response:
                        response.raise_for_status()
                        for chunk in response.iter_bytes(1024 * 1024):
                            check_cancel()
                            received += len(chunk)
                            if received > spec[0]:
                                raise ValueError(f'Breeze 檔案大小異常：{name}')
                            output.write(chunk)
                            update(f'下載 Breeze：{(completed + received) / total:.0%}', (completed + received) / total)
                    check_cancel()
                    if not file_valid(Path(temporary), spec):
                        raise ValueError(f'Breeze 檔案校驗失敗：{name}；未標記為可用。')
                    os.replace(temporary, root / name)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
                completed += spec[0]
        check_cancel()
        _write_manifest(root, manifest)
        update('Breeze 模型已下載並通過校驗；請使用音檔或錄音測試辨識。', 1)
        return root
    except httpx.HTTPError:
        raise ValueError('Breeze 下載失敗；請檢查網路後重試，已完成校驗的檔案會保留。') from None
    finally:
        lock.unlink(missing_ok=True)
