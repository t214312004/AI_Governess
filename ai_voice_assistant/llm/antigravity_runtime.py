"""Install, update and verify Google's official Antigravity ACP runtime.

Release lock copied from the official ACP registry on 2026-10-24:
https://github.com/agentclientprotocol/registry/blob/main/antigravity-acp/agent.json
Explicit updates consult that registry; normal startup stays offline and uses
the activated, verified bundle. The original release remains the install seed.
"""
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.request import urlopen
from uuid import uuid4
import zipfile

RUNTIME_VERSION = "1.4.3"
SERVER_NAME = "agy_acp_server.exe"
HELPER_NAME = "localharness_external.exe"
REGISTRY_URL = "https://raw.githubusercontent.com/agentclientprotocol/registry/main/antigravity-acp/agent.json"
RELEASES = {
    "AMD64": ("x86_64", "54c2e16378d9a4952e1da70e355f3c33c4f284308d6de48ab3e6e34a127bd325"),
    "ARM64": ("arm64", "fcd46431ad33d3b510ce0b98fe7b43d095bd8b3f1c363ee2d57faa7ee981c7bb"),
}
# Independently derived from the SHA256-verified x64 official ZIP above. This
# also rejects a valid Google-signed helper from a different release.
X64_FILE_HASHES = {
    SERVER_NAME: "012c6ec50e11e4d452b43e3b68fbbe2e8c88af8b11d0766e4d2d8e75b447d8e2",
    HELPER_NAME: "4d10117211a26059be464eb427eb69bc948b4363a82729059560a705e11d6932",
}
ARM64_FILE_HASHES = {
    SERVER_NAME: "4757a4459044010bfdd4748fac463ad4185369a4d3bd60757492c610406adf6c",
    HELPER_NAME: "3d18dc3b5235f35df07bc5847cbc6238bf1b28901f6129947b9f86094aad8386",
}
_INSTALL_LOCK = threading.Lock()
RECEIPT_NAME = "release.json"
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


@dataclass(frozen=True)
class RuntimeRelease:
    version: str
    architecture: str
    sha256: str

    @property
    def archive_url(self):
        return f"https://dl.google.com/agy-extensions/releases/windows/agy-acp-server-{self.version}-windows-{self.architecture}.zip"


def _machine():
    machine = platform.machine().upper()
    machine = "AMD64" if machine == "X86_64" else machine
    if os.name != "nt" or machine not in RELEASES:
        raise ValueError("官方 Antigravity ACP runtime 需要 Windows x64 或 ARM64。")
    return machine


def _version(value):
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise ValueError("Antigravity ACP release version 格式無效。")
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Antigravity ACP release SHA256 格式無效。")
    return value


def runtime_directory(version=RUNTIME_VERSION):
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise ValueError("找不到 Windows LOCALAPPDATA，無法定位 Antigravity ACP。")
    return Path(base) / "AI_Governess" / "runtimes" / "antigravity-acp" / _version(version)


def _active_version():
    pointer = runtime_directory().parent / "active.json"
    if not pointer.exists():
        return RUNTIME_VERSION
    try:
        data = json.loads(pointer.read_text(encoding="utf-8"))
        return _version(data["version"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("Antigravity ACP 啟用紀錄無效，請在初始設定安裝／更新以修復。") from exc


def _activate(release):
    root = runtime_directory().parent
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root,
                                         prefix=".active-", delete=False) as output:
            temporary = Path(output.name)
            json.dump({"version": release.version}, output)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, root / "active.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def latest_release(*, cancel, deadline):
    """Read the official ACP registry without invoking or installing the CLI."""
    _check(cancel, deadline)
    machine = _machine()
    try:
        with urlopen(REGISTRY_URL, timeout=max(1, min(10, deadline-time.monotonic()))) as response:
            if response.geturl() != REGISTRY_URL:
                raise ValueError("Antigravity ACP registry 來源不符。")
            raw = response.read(1024 * 1024 + 1)
        _check(cancel, deadline)
        if len(raw) > 1024 * 1024:
            raise ValueError("Antigravity ACP registry 超出大小上限。")
        data = json.loads(raw)
        if data.get("id") != "antigravity-acp" or "Google LLC" not in data.get("authors", []):
            raise ValueError("Antigravity ACP registry identity 不符。")
        version = _version(data.get("version"))
        architecture = RELEASES[machine][0]
        entry = data["distribution"]["binary"]["windows-aarch64" if machine == "ARM64" else "windows-x86_64"]
        release = RuntimeRelease(version, architecture, _hash(entry.get("sha256")))
        if (entry.get("archive") != release.archive_url or entry.get("cmd") != "./" + SERVER_NAME
                or entry.get("args", []) != [] or entry.get("env", {}) != {}):
            raise ValueError("Antigravity ACP registry packaging 已改變，請更新愛管家後再試。")
        if version == RUNTIME_VERSION and release.sha256 != RELEASES[machine][1]:
            raise ValueError("Antigravity ACP registry 與已驗證 release SHA256 不符。")
        return release
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("無法讀取官方 Antigravity ACP registry；既有安裝保持不變。") from exc


def _bundle_release(directory):
    """Use the immutable seed hashes, or a receipt from a verified update ZIP."""
    machine = _machine()
    architecture, checksum = RELEASES[machine]
    seed_hashes = ARM64_FILE_HASHES if machine == "ARM64" else X64_FILE_HASHES
    receipt = Path(directory) / RECEIPT_NAME
    if not receipt.exists():
        return RuntimeRelease(RUNTIME_VERSION, architecture, checksum), seed_hashes
    try:
        data = json.loads(receipt.read_text(encoding="utf-8"))
        release = RuntimeRelease(_version(data["version"]), data["architecture"], _hash(data["archive_sha256"]))
        hashes = data["file_sha256"]
        if (release.architecture != architecture or data["registry"] != REGISTRY_URL
                or data["archive"] != release.archive_url or set(hashes) != {SERVER_NAME, HELPER_NAME}):
            raise ValueError("Antigravity ACP release receipt 不符。")
        for digest in hashes.values():
            _hash(digest)
        if release.version == RUNTIME_VERSION and (release.sha256 != checksum or hashes != seed_hashes):
            raise ValueError("Antigravity ACP receipt 與已驗證 release 不符。")
        return release, hashes
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Antigravity ACP release receipt 無效；請安裝／更新以修復。") from exc


def _write_receipt(directory, release):
    payload = {"version": release.version, "architecture": release.architecture,
               "archive_sha256": release.sha256, "registry": REGISTRY_URL,
               "archive": release.archive_url,
               "file_sha256": {name: _sha256(Path(directory) / name) for name in (SERVER_NAME, HELPER_NAME)}}
    (Path(directory) / RECEIPT_NAME).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def subscription_environment(base=None):
    """Remove ambient API/Cloud billing routes without touching parent env."""
    env = dict(os.environ if base is None else base)
    forbidden = {
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GCLOUD_PROJECT",
        "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_QUOTA_PROJECT",
        "CLOUDSDK_AUTH_ACCESS_TOKEN", "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE",
        "GOOGLE_API_USE_MTLS_ENDPOINT", "GOOGLE_GEMINI_BASE_URL",
        "GEMINI_API_BASE_URL", "GEMINI_BASE_URL", "GOOGLE_API_BASE_URL",
    }
    for key in list(env):
        if key.upper() in forbidden or key.upper().startswith(("AGY_", "ANTIGRAVITY_", "GOOGLE_GENAI_")):
            env.pop(key)
    return env


def _sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@lru_cache(maxsize=32)
def _verify_binary(path, size, mtime_ns, ctime_ns, expected_hash):
    if expected_hash and _sha256(path) != expected_hash:
        raise ValueError(f"Antigravity ACP {Path(path).name} 不符合已驗證的 release SHA256。")
    # The path is passed in an environment variable; no shell interpolation of
    # user-controlled paths (spaces, Chinese, quotes) is involved.
    script = (
        "$ErrorActionPreference='Stop';"
        "$s=Get-AuthenticodeSignature -LiteralPath $env:AI_GOVERNESS_VERIFY_BINARY;"
        "@{status=[string]$s.Status;subject=[string]$s.SignerCertificate.Subject} | ConvertTo-Json -Compress"
    )
    env = os.environ.copy()
    env["AI_GOVERNESS_VERIFY_BINARY"] = path
    powershell_home = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "WindowsPowerShell" / "v1.0"
    # Codex/PowerShell 7 may prepend its own incompatible modules. Signature
    # verification runs in Windows PowerShell with its matching system modules.
    env["PSModulePath"] = str(powershell_home / "Modules")
    try:
        result = subprocess.run(
            [str(powershell_home / "powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=20, check=True, env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        signature = json.loads(result.stdout.decode("utf-8-sig"))
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
        raise ValueError("無法驗證 Antigravity ACP 的 Google Authenticode 簽章。") from exc
    if signature.get("status") != "Valid" or not re.search(
        r"(?:^|,\s*)(?:CN|O)=Google LLC(?:,|$)", signature.get("subject", "")
    ):
        raise ValueError(f"Antigravity ACP {Path(path).name} 缺少有效的 Google LLC 簽章。")


def verify_runtime(executable):
    """Require both official executables; reject partial or mixed installs."""
    server = Path(executable).expanduser().resolve()
    if os.name != "nt":
        raise ValueError("此 Antigravity ACP 安裝程式目前僅支援 Windows。")
    if server.name.lower() != SERVER_NAME:
        raise ValueError(f"Antigravity executable 必須是官方 {SERVER_NAME}。")
    _, hashes = _bundle_release(server.parent)
    for path in (server, server.with_name(HELPER_NAME)):
        if not path.is_file():
            raise ValueError(f"Antigravity ACP 缺少 {path.name}；請安裝／修復官方 ACP。")
        metadata = path.stat()
        expected = hashes[path.name]
        _verify_binary(str(path), metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns, expected)
    return server


def resolve_runtime_executable(configured=""):
    """Discover a configured bundle or the activated managed release, offline."""
    if configured and str(configured).strip():
        path = Path(str(configured).strip()).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
    else:
        version = _active_version()
        path = runtime_directory(version) / SERVER_NAME
        if not path.exists():
            return None
        release, _ = _bundle_release(path.parent)
        if release.version != version:
            raise ValueError("Antigravity ACP 啟用版本與 release receipt 不符，請安裝／更新以修復。")
    return str(verify_runtime(path))


def _check(cancel, deadline):
    if cancel.is_set():
        raise ValueError("Antigravity ACP 安裝已取消。")
    if time.monotonic() >= deadline:
        raise ValueError("Antigravity ACP 安裝逾時，既有安裝保持不變。")


def install_runtime(*, cancel, deadline, progress=None, force=False, update=False):
    """Verify a Google download in staging, then atomically activate it."""
    machine = _machine()
    _check(cancel, deadline)
    # No blocking lock acquisition that ignores the UI's cancel button.
    while not _INSTALL_LOCK.acquire(timeout=.1):
        _check(cancel, deadline)
    try:
        if update:
            if progress:
                progress("正在查詢官方 Antigravity ACP 最新 release；可取消。")
            release = latest_release(cancel=cancel, deadline=deadline)
            try:
                current = _active_version() if resolve_runtime_executable() else RUNTIME_VERSION
            except (OSError, ValueError):
                current = RUNTIME_VERSION  # Repair an invalid/incomplete activation.
            if tuple(map(int, release.version.split('.'))) < tuple(map(int, current.split('.'))):
                raise ValueError("官方 registry 版本較已啟用版本舊；保留既有版本，不自動降版。")
        else:
            architecture, checksum = RELEASES[machine]
            release = RuntimeRelease(RUNTIME_VERSION, architecture, checksum)
        target = runtime_directory(release.version)
        if target.exists() and not force:
            try:
                installed = str(verify_runtime(target / SERVER_NAME))
                actual, _ = _bundle_release(target)
                if actual != release:
                    raise ValueError("已安裝 bundle 與官方 release 不符。")
            except ValueError:
                pass  # Repair an incomplete install through verified staging.
            else:
                _check(cancel, deadline)
                _activate(release)
                if progress:
                    progress(f"官方 ACP {release.version} 已是可用版本；正在查詢模型。")
                return installed
        root = target.parent
        root.mkdir(parents=True, exist_ok=True)
        url = release.archive_url
        if progress:
            progress(f"正在下載官方 Antigravity ACP {release.version}；可取消。")
        with tempfile.TemporaryDirectory(prefix=".install-", dir=root) as temporary:
            staging = Path(temporary)
            archive = staging / "runtime.zip"
            digest = hashlib.sha256()
            total = 0
            try:
                with urlopen(url, timeout=max(1, min(10, deadline - time.monotonic()))) as response, archive.open("wb") as output:
                    # A redirect must remain on Google's official download host.
                    from urllib.parse import urlparse
                    actual_url = urlparse(response.geturl())
                    if actual_url.scheme != "https" or actual_url.hostname != "dl.google.com":
                        raise ValueError("Antigravity ACP 下載來源不是官方 dl.google.com。")
                    while True:
                        _check(cancel, deadline)
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > 400 * 1024 * 1024:
                            raise ValueError("Antigravity ACP 下載超出大小上限。")
                        digest.update(chunk)
                        output.write(chunk)
            except OSError as exc:
                raise ValueError("無法下載官方 Antigravity ACP，請檢查網路後重試。") from exc
            if digest.hexdigest() != release.sha256:
                raise ValueError("Antigravity ACP archive SHA256 不符；未安裝下載內容。")
            if progress:
                progress("正在驗證官方 archive、Google 簽章與配套 harness。")
            bundle = staging / "bundle"
            bundle.mkdir()
            with zipfile.ZipFile(archive) as package:
                if sorted(package.namelist()) != sorted((SERVER_NAME, HELPER_NAME)):
                    raise ValueError("Antigravity ACP archive 內容與已驗證 release 不符。")
                if sum(item.file_size for item in package.infolist()) > 700 * 1024 * 1024:
                    raise ValueError("Antigravity ACP 解壓大小超出上限。")
                for name in (SERVER_NAME, HELPER_NAME):
                    _check(cancel, deadline)
                    with package.open(name) as source, (bundle / name).open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
            _write_receipt(bundle, release)
            verify_runtime(bundle / SERVER_NAME)
            _check(cancel, deadline)
            # Keep the rollback copy outside TemporaryDirectory: if restoring a
            # Windows in-use directory fails, cleanup must never delete the last
            # known install. A retained .previous-* directory is recoverable.
            backup = root / f".previous-{uuid4().hex}"
            if target.exists():
                try:
                    target.rename(backup)
                except OSError as exc:
                    raise ValueError("Antigravity ACP 正在使用中，請關閉該 backend 後再修復。") from exc
            activated = False
            try:
                bundle.rename(target)
                activated = True
                installed = str(verify_runtime(target / SERVER_NAME))
                _check(cancel, deadline)
                _activate(release)
            except BaseException:
                if activated:
                    target.rename(bundle)
                if backup.exists():
                    backup.rename(target)
                raise
            if backup.exists():
                if backup.resolve().parent != root.resolve():
                    raise ValueError("Antigravity ACP 舊版清理路徑超出受控安裝目錄。")
                try:
                    shutil.rmtree(backup)
                except OSError:
                    if progress:
                        progress("官方 ACP 已安裝；舊 runtime 正在使用中，保留 .previous-* 備份。")
            return installed
    finally:
        _INSTALL_LOCK.release()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "update", "verify"))
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()
    try:
        result = (install_runtime(cancel=threading.Event(), deadline=time.monotonic() + 300,
                                  progress=print, force=args.repair, update=args.action == "update")
                  if args.action in ("install", "update") else resolve_runtime_executable())
        if not result:
            raise ValueError("尚未安裝官方 Antigravity ACP。")
        print(result)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + "\n")
