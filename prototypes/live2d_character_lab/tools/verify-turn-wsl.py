"""Reopen and verify a saved v10 or v11 model using PSD2Live on WSL2."""
import argparse
import hashlib
import json
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

lab = Path(__file__).resolve().parents[1]
cache = lab / '.cache/psd2live-linux-v3.6.7'
sys.path.insert(0, str(lab / 'vendor'))
from mcp_proxy import Client

archive = cache / 'PSD2Live-3.6.7-linux-x64.tar.gz'
archive_sha256 = 'ac788290387ca5b373d445f9f879185de3b4102373487b389e3adab0e433b686'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_export(work, source, base_model, report_path):
    subprocess.run(['tar', '-xf', str(archive), '-C', str(work)], check=True)
    project_copy = work / source.name
    shutil.copy2(source, project_copy)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    token = secrets.token_hex(32)
    app = work / 'PSD2Live/bin/PSD2Live'
    command = [str(app), 'mcp', '--port', str(port), '--token', token, '--store', str(work / 'store')]
    with (work / 'server.log').open('wb') as log:
        service = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            for attempt in range(60):
                if service.poll() is not None:
                    details = (work / 'server.log').read_text(errors='replace').replace(token, '[redacted]')
                    raise RuntimeError(f'PSD2Live exited before listening ({service.returncode}): {details[-1600:]}')
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=1):
                        break
                except OSError:
                    time.sleep(0.5)
            else:
                raise RuntimeError('The PSD2Live service did not start in 30 seconds')
            print('Linux PSD2Live MCP is listening.', flush=True)
            with Client(endpoint=f'http://127.0.0.1:{port}/mcp', token=token) as client:
                client.edit('project_open', path=str(project_copy), discard_unsaved=True)
                print(f'Opened a copy of {source.name}.', flush=True)
                output = work / 'export'
                client.edit('project_export_model', output_directory=str(output))
            expected = [base_model / 'original.moc3', *sorted(base_model.rglob('texture_*.png'))]
            checks = {}
            hashes = {}
            for baseline in expected:
                relative = baseline.relative_to(base_model)
                actual = output / relative
                key = relative.as_posix()
                hashes[key] = digest(actual) if actual.is_file() else None
                checks[key] = hashes[key] == digest(baseline)
            report = {
                'linux_export_checks': checks,
                'exported_sha256': hashes,
                'exported_files': sorted(f.relative_to(output).as_posix() for f in output.rglob('*') if f.is_file()),
            }
            report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(report, indent=2), flush=True)
            if not all(checks.values()):
                shutil.copytree(output, cache / f'export-{work.name}')
                return 1
            return 0
        finally:
            service.terminate()
            try:
                service.wait(timeout=10)
            except subprocess.TimeoutExpired:
                service.kill()
                service.wait()


if __name__ == '__main__':
    if not archive.is_file():
        sys.exit(f'Missing official Linux archive: {archive}')
    if digest(archive) != archive_sha256:
        sys.exit('PSD2Live archive SHA-256 differs from the official v3.6.7 Linux x64 package.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--polish', action='store_true', help='Verify the native v11 model')
    args = parser.parse_args()
    if args.polish:
        source = lab / 'authoring/polish-v11/shared-face-rig-v11-polish.psd2live'
        base_model = lab / 'models/polish-face'
        report_path = lab / 'reports/g2/v11-linux-roundtrip.json'
    else:
        source = lab / 'authoring/turn-v10/shared-face-rig-v10-turn.psd2live'
        base_model = lab / 'models/turn-face'
        report_path = lab / 'reports/g2/v10-linux-roundtrip.json'
    with tempfile.TemporaryDirectory(prefix='psd2live-roundtrip-') as folder:
        sys.exit(check_export(Path(folder), source, base_model, report_path))
