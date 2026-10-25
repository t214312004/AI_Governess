"""Official bundle install/update and subscription-only setup boundaries."""
import asyncio
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from unittest.mock import AsyncMock, MagicMock
import zipfile

import pytest

from core.settings_schema import SettingsError, field_spec, validate_field
from llm import antigravity_runtime as runtime
from llm.acp_stdio_client import ACPStdioClient
from llm.model_catalog import CliCatalog


def test_subscription_environment_strips_billing_routes_without_mutating_parent():
    original = {
        'PATH': 'safe', 'AI_GOVERNESS_APP_DIR': 'app', 'GEMINI_HOME': 'personal-home',
        'GEMINI_API_KEY': 'private', 'Google_Api_Key': 'private',
        'GOOGLE_APPLICATION_CREDENTIALS': 'cloud.json', 'GOOGLE_CLOUD_PROJECT': 'paid',
        'GOOGLE_GENAI_USE_VERTEXAI': '1', 'CLOUDSDK_AUTH_ACCESS_TOKEN': 'private',
        'AGY_API_URL': 'provider-override', 'ANTIGRAVITY_AUTH': 'api',
    }
    before = original.copy()
    clean = runtime.subscription_environment(original)
    assert clean == {'PATH': 'safe', 'AI_GOVERNESS_APP_DIR': 'app', 'GEMINI_HOME': 'personal-home'}
    assert original == before


@pytest.mark.skipif(os.name != 'nt', reason='Windows official signed bundle')
def test_partial_or_mixed_runtime_is_rejected(tmp_path, monkeypatch):
    server = tmp_path / runtime.SERVER_NAME
    server.write_bytes(b'server')
    monkeypatch.setattr(runtime, '_verify_binary', lambda *args: None)
    with pytest.raises(ValueError, match=runtime.HELPER_NAME):
        runtime.verify_runtime(server)
    helper = tmp_path / runtime.HELPER_NAME
    helper.write_bytes(b'wrong-release')
    monkeypatch.undo()
    with pytest.raises(ValueError, match='release'):
        runtime.verify_runtime(server)


@pytest.mark.skipif(os.name != 'nt', reason='Windows Authenticode')
def test_signature_verifier_requires_valid_google_and_keeps_paths_out_of_script(tmp_path, monkeypatch):
    runtime._verify_binary.cache_clear()
    binary = tmp_path / "家人's folder" / runtime.SERVER_NAME
    binary.parent.mkdir()
    binary.write_bytes(b'binary')
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps({
            'status': 'Valid', 'subject': 'CN=Another Company, O=Another Company'}).encode(), b'')
    monkeypatch.setattr(runtime.subprocess, 'run', run)
    with pytest.raises(ValueError, match='Google LLC'):
        runtime._verify_binary(str(binary), 6, 1, 1, None)
    command, kwargs = calls[0]
    assert str(binary) not in command[-1]
    assert kwargs['env']['AI_GOVERNESS_VERIFY_BINARY'] == str(binary)
    assert kwargs['env']['PSModulePath'].endswith('WindowsPowerShell\\v1.0\\Modules')


class Download(io.BytesIO):
    def geturl(self):
        return 'https://dl.google.com/official-test.zip'


@pytest.fixture
def official_bundle(tmp_path, monkeypatch):
    if os.name != 'nt':
        pytest.skip('Windows official bundle')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(runtime.platform, 'machine', lambda: 'AMD64')
    contents = {runtime.SERVER_NAME: b'official-server', runtime.HELPER_NAME: b'official-helper'}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    payload = stream.getvalue()
    monkeypatch.setitem(runtime.RELEASES, 'AMD64', ('x86_64', hashlib.sha256(payload).hexdigest()))
    monkeypatch.setattr(runtime, 'X64_FILE_HASHES', {
        name: hashlib.sha256(data).hexdigest() for name, data in contents.items()})
    verified = []
    def verify(path, size, mtime_ns, ctime_ns, checksum):
        if runtime._sha256(path) != checksum:
            raise ValueError('release SHA256 mismatch')
        verified.append(Path(path).name)
    monkeypatch.setattr(runtime, '_verify_binary', verify)
    monkeypatch.setattr(runtime, 'urlopen', lambda *args, **kwargs: Download(payload))
    return payload, contents, verified


@pytest.fixture
def future_release(official_bundle, monkeypatch):
    contents = {runtime.SERVER_NAME: b'future-server', runtime.HELPER_NAME: b'future-matching-helper'}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    payload = stream.getvalue()
    release = runtime.RuntimeRelease('1.5.0', 'x86_64', hashlib.sha256(payload).hexdigest())
    manifest = {'id': 'antigravity-acp', 'authors': ['Google LLC'], 'version': release.version,
                'distribution': {'binary': {'windows-x86_64': {
                    'archive': release.archive_url, 'cmd': './' + runtime.SERVER_NAME, 'sha256': release.sha256}}}}
    calls = []
    class RegistryDownload(Download):
        def geturl(self):
            return runtime.REGISTRY_URL
    def fetch(url, **kwargs):
        calls.append(url)
        if url == runtime.REGISTRY_URL:
            return RegistryDownload(json.dumps(manifest).encode())
        assert url == release.archive_url
        return Download(payload)
    monkeypatch.setattr(runtime, 'urlopen', fetch)
    return release, manifest, contents, calls


def test_registry_update_activates_new_bundle_and_discovery_is_offline(future_release, monkeypatch):
    release, _, contents, calls = future_release
    executable = runtime.install_runtime(cancel=threading.Event(), deadline=time.monotonic()+10, update=True)
    target = runtime.runtime_directory(release.version).resolve()
    assert Path(executable).parent == target
    assert all((target / name).read_bytes() == data for name, data in contents.items())
    assert calls == [runtime.REGISTRY_URL, release.archive_url]
    receipt = json.loads((target / runtime.RECEIPT_NAME).read_text())
    assert receipt['archive_sha256'] == release.sha256
    assert receipt['file_sha256'][runtime.HELPER_NAME] == hashlib.sha256(contents[runtime.HELPER_NAME]).hexdigest()
    monkeypatch.setattr(runtime, 'urlopen', lambda *a, **k: pytest.fail('startup must stay offline'))
    assert runtime.resolve_runtime_executable() == executable
    assert runtime.resolve_runtime_executable(executable) == executable


def test_latest_already_installed_is_verified_without_another_archive_download(future_release):
    release, _, _, calls = future_release
    kwargs = dict(cancel=threading.Event(), deadline=time.monotonic()+10, update=True)
    executable = runtime.install_runtime(**kwargs)
    assert runtime.install_runtime(**kwargs) == executable
    assert calls == [runtime.REGISTRY_URL, release.archive_url, runtime.REGISTRY_URL]


def test_successful_update_keeps_previous_version_available(future_release):
    _, _, _, _ = future_release
    previous = runtime.runtime_directory()
    previous.mkdir(parents=True)
    previous_bytes = b'previous-version-kept-for-explicit-rollback'
    (previous / runtime.SERVER_NAME).write_bytes(previous_bytes)
    (previous.parent / 'active.json').write_text(json.dumps({'version': runtime.RUNTIME_VERSION}))
    executable = runtime.install_runtime(cancel=threading.Event(), deadline=time.monotonic()+10, update=True)
    assert Path(executable).parent != previous
    assert (previous / runtime.SERVER_NAME).read_bytes() == previous_bytes


def test_failed_activation_preserves_previous_bundle_and_pointer(future_release, monkeypatch):
    release, _, _, _ = future_release
    previous = runtime.runtime_directory()
    previous.mkdir(parents=True)
    (previous / runtime.SERVER_NAME).write_bytes(b'previous-owned-bundle')
    root = previous.parent
    (root / 'active.json').write_text(json.dumps({'version': runtime.RUNTIME_VERSION}))
    before = (root / 'active.json').read_bytes()
    def fail_activation(_release):
        raise OSError('synthetic disk write failure')
    monkeypatch.setattr(runtime, '_activate', fail_activation)
    with pytest.raises(OSError, match='synthetic disk'):
        runtime.install_runtime(cancel=threading.Event(), deadline=time.monotonic()+10, update=True)
    assert (previous / runtime.SERVER_NAME).read_bytes() == b'previous-owned-bundle'
    assert (root / 'active.json').read_bytes() == before
    assert not runtime.runtime_directory(release.version).exists()
    assert not list(root.glob('.install-*'))


def test_registry_network_failure_leaves_existing_install_unchanged(future_release, monkeypatch):
    target = runtime.runtime_directory()
    target.mkdir(parents=True)
    (target / runtime.SERVER_NAME).write_bytes(b'previous')
    def unavailable(*args, **kwargs):
        raise OSError('synthetic network unavailable')
    monkeypatch.setattr(runtime, 'urlopen', unavailable)
    with pytest.raises(ValueError, match='既有安裝保持不變'):
        runtime.install_runtime(cancel=threading.Event(), deadline=time.monotonic()+10, update=True)
    assert (target / runtime.SERVER_NAME).read_bytes() == b'previous'


@pytest.mark.parametrize('change', ['identity', 'author', 'version', 'archive', 'command', 'args', 'hash'])
def test_registry_rejects_invalid_identity_packaging_and_release_paths(future_release, change):
    _, manifest, _, calls = future_release
    entry = manifest['distribution']['binary']['windows-x86_64']
    if change == 'identity': manifest['id'] = 'another-agent'
    elif change == 'author': manifest['authors'] = ['Another Publisher']
    elif change == 'version': manifest['version'] = '../outside'
    elif change == 'archive': entry['archive'] = 'https://example.invalid/untrusted.zip'
    elif change == 'command': entry['cmd'] = './another.exe'
    elif change == 'args': entry['args'] = ['new-unsupported-option']
    else: entry['sha256'] = 'invalid'
    with pytest.raises(ValueError):
        runtime.latest_release(cancel=threading.Event(), deadline=time.monotonic()+10)
    assert calls == [runtime.REGISTRY_URL]


def test_registry_update_does_not_silently_downgrade_active_version(future_release):
    release, _, contents, _ = future_release
    root = runtime.runtime_directory().parent
    previous = runtime.runtime_directory('2.0.0')
    previous.mkdir(parents=True)
    for name, data in contents.items():
        (previous / name).write_bytes(data)
    runtime._write_receipt(previous, runtime.RuntimeRelease('2.0.0', 'x86_64', release.sha256))
    (root / 'active.json').write_text('{"version":"2.0.0"}')
    with pytest.raises(ValueError, match='不自動降版'):
        runtime.install_runtime(cancel=threading.Event(), deadline=time.monotonic()+10, update=True)
    assert json.loads((root / 'active.json').read_text())['version'] == '2.0.0'


def test_registry_update_repairs_activation_pointing_to_missing_bundle(future_release):
    release, _, _, _ = future_release
    root = runtime.runtime_directory().parent
    root.mkdir(parents=True)
    (root / 'active.json').write_text('{"version":"2.0.0"}')
    executable = runtime.install_runtime(cancel=threading.Event(), deadline=time.monotonic()+10, update=True)
    assert Path(executable).parent == runtime.runtime_directory(release.version).resolve()
    assert runtime.resolve_runtime_executable() == executable


def test_updated_matching_helper_is_checked_against_install_receipt(future_release):
    executable = runtime.install_runtime(cancel=threading.Event(), deadline=time.monotonic()+10, update=True)
    Path(executable).with_name(runtime.HELPER_NAME).write_bytes(b'another-release-helper')
    with pytest.raises(ValueError, match='SHA256'):
        runtime.verify_runtime(executable)


def test_managed_active_version_must_match_receipt(future_release):
    release, _, _, _ = future_release
    executable = runtime.install_runtime(cancel=threading.Event(), deadline=time.monotonic()+10, update=True)
    target = runtime.runtime_directory('1.6.0')
    target.mkdir()
    import shutil
    for name in (runtime.SERVER_NAME, runtime.HELPER_NAME, runtime.RECEIPT_NAME):
        shutil.copy2(Path(executable).parent / name, target / name)
    (target.parent / 'active.json').write_text('{"version":"1.6.0"}')
    with pytest.raises(ValueError, match='啟用版本'):
        runtime.resolve_runtime_executable()


def test_cancelled_update_never_fetches_registry_or_changes_activation(future_release):
    _, _, _, calls = future_release
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ValueError, match='取消'):
        runtime.install_runtime(cancel=cancel, deadline=time.monotonic()+10, update=True)
    assert calls == []


@pytest.mark.skipif(os.name != 'nt', reason='Windows official bundle')
def test_install_verifies_both_binaries_then_activates_complete_bundle(official_bundle):
    _, contents, verified = official_bundle
    executable = runtime.install_runtime(cancel=threading.Event(), deadline=time.monotonic()+10)
    assert Path(executable).parent == runtime.runtime_directory().resolve()
    assert all((Path(executable).parent / name).read_bytes() == data for name, data in contents.items())
    assert set(verified) == {runtime.SERVER_NAME, runtime.HELPER_NAME}
    assert not list(runtime.runtime_directory().parent.glob('.install-*'))


@pytest.mark.skipif(os.name != 'nt', reason='Windows official bundle')
def test_checksum_failure_preserves_previous_install(official_bundle, monkeypatch):
    target = runtime.runtime_directory()
    target.mkdir(parents=True)
    (target / runtime.SERVER_NAME).write_bytes(b'previous')
    monkeypatch.setattr(runtime, 'urlopen', lambda *args, **kwargs: Download(b'corrupted'))
    with pytest.raises(ValueError, match='SHA256'):
        runtime.install_runtime(cancel=threading.Event(), deadline=time.monotonic()+10, force=True)
    assert (target / runtime.SERVER_NAME).read_bytes() == b'previous'
    assert not list(target.parent.glob('.install-*'))


@pytest.mark.skipif(os.name != 'nt', reason='Windows official bundle')
def test_post_activation_verification_failure_restores_previous_install(official_bundle, monkeypatch):
    target = runtime.runtime_directory()
    target.mkdir(parents=True)
    (target / runtime.SERVER_NAME).write_bytes(b'previous')
    verify = runtime.verify_runtime
    def reject_final(executable):
        if Path(executable).parent == target:
            raise ValueError('post-activation verification failed')
        return verify(executable)
    monkeypatch.setattr(runtime, 'verify_runtime', reject_final)
    with pytest.raises(ValueError, match='post-activation'):
        runtime.install_runtime(cancel=threading.Event(), deadline=time.monotonic()+10, force=True)
    assert (target / runtime.SERVER_NAME).read_bytes() == b'previous'
    assert not list(target.parent.glob('.previous-*'))
    assert not list(target.parent.glob('.install-*'))


@pytest.mark.skipif(os.name != 'nt', reason='Windows official bundle')
def test_cancelled_download_preserves_previous_install(official_bundle, monkeypatch):
    payload, _, _ = official_bundle
    target = runtime.runtime_directory()
    target.mkdir(parents=True)
    (target / runtime.SERVER_NAME).write_bytes(b'previous')
    cancel = threading.Event()
    class CancelDownload(Download):
        def read(self, count):
            cancel.set()
            return super().read(count)
    monkeypatch.setattr(runtime, 'urlopen', lambda *args, **kwargs: CancelDownload(payload))
    with pytest.raises(ValueError, match='取消'):
        runtime.install_runtime(cancel=cancel, deadline=time.monotonic()+10, force=True)
    assert (target / runtime.SERVER_NAME).read_bytes() == b'previous'


def test_antigravity_discovery_does_not_search_for_old_agy(monkeypatch):
    monkeypatch.setattr(runtime, 'resolve_runtime_executable', lambda configured: None)
    monkeypatch.setattr('llm.model_catalog.shutil.which', lambda _: pytest.fail('legacy CLI discovery'))
    with pytest.raises(ValueError, match='ACP'):
        CliCatalog._executable('antigravity_cli', {'llm': {'antigravity_cli': {}}})


def test_catalog_login_is_explicit_and_excludes_private_mcp_context(monkeypatch):
    client = MagicMock()
    client.ensure_ready = AsyncMock()
    client.authenticate_personal = AsyncMock(return_value=True)
    client.aclose = AsyncMock()
    client._find_config_option = ACPStdioClient._find_config_option
    client._config_option_values = ACPStdioClient._config_option_values
    client._set_config_option = AsyncMock()
    client._session_config_options = [
        {'id': 'model', 'category': 'model', 'options': [{'value': 'gemini-current'}]},
        {'id': 'thinking_level', 'category': 'thought_level', 'options': [{'value': 'low'}]},
    ]
    settings = {'llm': {'antigravity_cli': {'effort': 'private-selection',
        'mcp_servers': [{'name': 'private', 'command': 'do-not-run'}]}}}
    original = deepcopy(settings)
    def factory(backend, **options):
        assert backend == 'antigravity_cli'
        assert not options['load_private_context'] and options['mcp_servers'] == []
        assert options['effort'] == '' and options['mode'] == 'yolo'
        for name in options['required_context_files']:
            assert Path(options['project_dir'], name).read_text() == ''
        return client
    monkeypatch.setattr('llm.client_factory.create_llm_client', factory)
    catalog = CliCatalog(lambda: settings)
    for explicit in (False, True):
        models = asyncio.run(catalog._query_protocol('antigravity_cli', settings,
            threading.Event(), time.monotonic()+5, authenticate=explicit))
        assert [(model.id, model.efforts) for model in models] == [('gemini-current', ('low',))]
    client.authenticate_personal.assert_awaited_once()
    assert client._catalog_only is True
    assert client.aclose.await_count == 2
    assert settings == original


def test_catalog_update_queries_new_managed_server_even_with_explicit_old_path(monkeypatch):
    from llm.model_catalog import ModelInfo
    settings = {'llm': {'antigravity_cli': {'executable': 'old-official-bundle/agy_acp_server.exe'}}}
    original = deepcopy(settings)
    installer = MagicMock(return_value='new-managed-bundle/agy_acp_server.exe')
    monkeypatch.setattr(runtime, 'install_runtime', installer)
    seen = []
    def executable(backend, options):
        seen.append(options['llm'][backend]['executable'])
        return seen[-1]
    catalog = CliCatalog(lambda: settings)
    monkeypatch.setattr(catalog, '_executable', executable)
    async def query(backend, options, *args, **kwargs):
        assert options['llm'][backend]['executable'] == 'new-managed-bundle/agy_acp_server.exe'
        return (ModelInfo('gemini-current', ('low',)),)
    monkeypatch.setattr(catalog, '_query_protocol', query)
    models = catalog.query('antigravity_cli', True, cancel=threading.Event())
    assert models[0].id == 'gemini-current'
    assert seen == ['new-managed-bundle/agy_acp_server.exe']
    assert installer.call_args.kwargs['update'] is True
    assert settings == original


@pytest.mark.skipif(os.environ.get('AI_GOVERNESS_NATIVE_TESTS') != '1', reason='Opt-in native Tk setup')
def test_native_update_button_requests_latest_and_persists_managed_selection(monkeypatch):
    import customtkinter as ctk
    from core.settings_schema import public_defaults
    from llm.model_catalog import ModelInfo
    from ui.startup import StartupView
    monkeypatch.setattr(CliCatalog, '_executable', lambda *args: runtime.SERVER_NAME)
    settings = deepcopy(public_defaults())
    settings['llm']['active_backend'] = 'antigravity_cli'
    settings['llm']['antigravity_cli']['executable'] = 'old-explicit/agy_acp_server.exe'
    catalog = CliCatalog(lambda: {})
    query = MagicMock(return_value=(ModelInfo('gemini-current', ('low',)),))
    monkeypatch.setattr(catalog, 'query', query)
    root = ctk.CTk()
    root.withdraw()
    view = StartupView(root, settings, lambda *args: None, catalog=catalog)
    try:
        assert view.update_button.cget('text') == '安裝／更新官方 ACP 並查詢模型'
        view.update_button.invoke()
        view.query_thread.join(timeout=2)
        view.poll_query()
        assert view.ready
        assert query.call_args.args == ('antigravity_cli', True)
        assert view.draft_snapshot()['llm']['antigravity_cli']['executable'] == ''
        assert settings['llm']['antigravity_cli']['executable'] == 'old-explicit/agy_acp_server.exe'
    finally:
        view.destroy()
        for job in root.tk.call('after', 'info'):
            root.after_cancel(job)
        root.destroy()


@pytest.mark.parametrize('key,value', [('auth_method', 'api-key'), ('subscription_only', False)])
def test_antigravity_schema_rejects_non_subscription_route(key, value):
    with pytest.raises(SettingsError):
        validate_field(('llm', 'antigravity_cli', key), value)
    assert field_spec(('llm', 'antigravity_cli', 'mcp_servers'), []).kind == 'json_list'


@pytest.mark.parametrize('value', ['C:/task', [None], [42], [''], ['   ']])
def test_filesystem_scope_schema_rejects_invalid_path_lists(value):
    with pytest.raises(SettingsError):
        validate_field(('llm', 'antigravity_cli', 'filesystem_roots'), value)


@pytest.mark.parametrize('backend,model,effort,expected', [
    ('antigravity_cli', 'gemini-4-argon-low', '', ('gemini-4-argon', 'low')),
    ('antigravity_cli', 'gemini-3.8-flash-medium', 'medium', ('gemini-3.8-flash', 'medium')),
    ('antigravity_cli', 'gemini-4-argon-low', 'high', ('gemini-4-argon-low', 'high')),
    ('antigravity_cli', 'claude-legacy', '', ('claude-legacy', '')),
    ('opencode_cli', 'gemini-4-argon-low', '', ('gemini-4-argon-low', '')),
])
def test_startup_preserves_legacy_model_variant_selection(backend, model, effort, expected):
    from ui.startup import preferred_selection
    assert preferred_selection(backend, model, effort) == expected


@pytest.mark.skipif(os.environ.get('AI_GOVERNESS_NATIVE_TESTS') != '1', reason='Opt-in native Tk setup')
@pytest.mark.parametrize('old_model,old_effort,requires_choice', [
    ('gemini-4-argon-low', '', False),
    ('claude-legacy', '', True),
    ('gemini-4-argon-low', 'high', True),
    ('gemini-4-argon', 'retired-effort', True),
])
def test_native_catalog_migration_never_silently_changes_model_or_effort(monkeypatch, old_model, old_effort, requires_choice):
    import customtkinter as ctk
    from core.settings_schema import public_defaults
    from llm.model_catalog import ModelInfo
    from ui.startup import StartupView
    monkeypatch.setattr(CliCatalog, '_executable', lambda *args: runtime.SERVER_NAME)
    settings = deepcopy(public_defaults())
    settings['llm']['active_backend'] = 'antigravity_cli'
    settings['llm']['antigravity_cli'].update(model=old_model, effort=old_effort)
    catalog = MagicMock()
    catalog.query.return_value = (ModelInfo('gemini-3.8-flash', ('low', 'high')),
                                  ModelInfo('gemini-4-argon', ('low', 'high')))
    root = ctk.CTk()
    root.withdraw()
    view = StartupView(root, settings, lambda *args: None, catalog=catalog)
    try:
        view.query(advance_after=True)
        view.query_thread.join(timeout=2)
        view.poll_query()
        assert view.ready
        if requires_choice:
            assert view.step == 0
            assert view.model.get() == '請選擇模型'
            assert view.model_menu.cget('state') == 'readonly'
            assert '重新選擇' in view.status.full_text
            assert view.draft_snapshot()['llm']['antigravity_cli']['model'] == old_model
            view.advance()
            assert view.step == 0
            view.model.set('gemini-4-argon')
            view.select_model('gemini-4-argon')
            view.advance()
            assert view.step == 1
        else:
            assert view.step == 1
            assert (view.model.get(), view.effort.get()) == ('gemini-4-argon', 'low')
    finally:
        view.destroy()
        for job in root.tk.call('after', 'info'):
            root.after_cancel(job)
        root.destroy()


@pytest.mark.skipif(os.environ.get('AI_GOVERNESS_NATIVE_TESTS') != '1', reason='Opt-in native Tk setup')
def test_native_startup_login_button_requests_only_explicit_personal_login(monkeypatch):
    import customtkinter as ctk
    from core.settings_schema import public_defaults
    from llm.model_catalog import ModelInfo
    from ui.startup import StartupView
    monkeypatch.setattr(CliCatalog, '_executable', lambda *args: runtime.SERVER_NAME)
    calls = []
    catalog = CliCatalog(lambda: {})
    def query(*args, **kwargs):
        calls.append((args, kwargs))
        return (ModelInfo('gemini-current', ('low',)),)
    monkeypatch.setattr(catalog, 'query', query)
    root = ctk.CTk()
    root.withdraw()
    view = StartupView(root, deepcopy(public_defaults()), lambda *args: None, catalog=catalog)
    try:
        assert view.auth_button.cget('text') == '登入 Google AI Pro 並查詢模型'
        assert '官方 ACP' in view.update_button.cget('text')
        view.auth_button.invoke()
        view.query_thread.join(timeout=2)
        view.poll_query()
        assert view.ready
        assert calls[0][0] == ('antigravity_cli', False)
        assert calls[0][1]['authenticate'] is True
        assert calls[0][1]['timeout'] == 480
    finally:
        view.destroy()
        for job in root.tk.call('after', 'info'):
            root.after_cancel(job)
        root.destroy()
