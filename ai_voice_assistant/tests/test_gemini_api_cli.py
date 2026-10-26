"""CLI maintenance integrity, read-only discovery and native startup persistence."""
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import threading
import time
from unittest.mock import Mock
import zipfile

import pytest

from config import Config
from core.session_settings import validate_settings
from core.settings_schema import public_defaults, SettingsError
from utils import gemini_api_cli as cli


def archive(binary=b'MZfake executable'):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as bundle:
        bundle.writestr('gemini-api.exe', binary)
    return output.getvalue()


@pytest.fixture
def release(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(cli.platform, 'machine', lambda: 'AMD64')
    data = archive()
    name = 'gemini-api_Windows_x86_64.zip'
    url = f'https://github.com/{cli.REPOSITORY}/releases/download/v0.4.4/{name}'
    metadata = {'tag_name': 'v0.4.4', 'assets': [{'name': name,
        'browser_download_url': url, 'digest': 'sha256:'+hashlib.sha256(data).hexdigest()}]}
    def download(source, cancel, deadline, maximum):
        cli._check(cancel, deadline)
        return json.dumps(metadata).encode() if source == cli.RELEASE_URL else data
    mock = Mock(side_effect=download)
    monkeypatch.setattr(cli, '_download', mock)
    return metadata, data, mock


def install(**kwargs):
    return cli.install_cli(cancel=threading.Event(), deadline=time.monotonic()+5, **kwargs)


@pytest.mark.skipif(os.name != 'nt', reason='Windows CLI installation')
def test_verified_update_is_discovered_offline_and_does_not_reinstall(release):
    _, data, download = release
    result = install()
    assert Path(result['executable']).read_bytes() == b'MZfake executable'
    assert cli.resolve_executable() == result['executable']
    receipt = json.loads((cli.runtime_root()/'active.json').read_text())
    assert receipt['archive_sha256'] == hashlib.sha256(data).hexdigest()
    assert not install()['updated']
    assert download.call_count == 3  # metadata+archive, then metadata only
    Path(result['executable']).write_bytes(b'MZtampered')
    with pytest.raises(ValueError, match='無效'):
        cli.resolve_executable()


@pytest.mark.skipif(os.name != 'nt', reason='Windows CLI installation')
def test_bad_digest_preserves_active_install_and_previous_binary(release):
    metadata, _, _ = release
    old = install()
    pointer = (cli.runtime_root()/'active.json').read_bytes()
    metadata['tag_name'] = 'v0.4.5'
    metadata['assets'][0]['browser_download_url'] = metadata['assets'][0]['browser_download_url'].replace('v0.4.4','v0.4.5')
    metadata['assets'][0]['digest'] = 'sha256:'+'0'*64
    with pytest.raises(ValueError, match='SHA256'):
        install()
    assert (cli.runtime_root()/'active.json').read_bytes() == pointer
    assert Path(old['executable']).read_bytes() == b'MZfake executable'


@pytest.mark.skipif(os.name != 'nt', reason='Windows CLI installation')
def test_untrusted_asset_url_and_cancel_never_change_activation(release):
    metadata, _, download = release
    old = install()
    metadata['assets'][0]['browser_download_url'] = 'https://example.org/gemini-api.zip'
    with pytest.raises(ValueError, match='格式無效'):
        install()
    assert cli.resolve_executable() == old['executable']
    cancel = threading.Event()
    cancel.set()
    download.reset_mock()
    with pytest.raises(ValueError, match='取消'):
        cli.install_cli(cancel=cancel, deadline=time.monotonic()+5)
    download.assert_not_called()


@pytest.mark.skipif(os.name != 'nt', reason='Windows CLI installation')
def test_cancel_before_activation_keeps_old_pointer(release, monkeypatch):
    metadata, _, download = release
    old = install()
    pointer = (cli.runtime_root()/'active.json').read_bytes()
    metadata['tag_name'] = 'v0.4.5'
    metadata['assets'][0]['browser_download_url'] = metadata['assets'][0]['browser_download_url'].replace('v0.4.4','v0.4.5')
    cancel = threading.Event()
    original = download.side_effect
    def cancel_download(source, event, deadline, maximum):
        data = original(source, event, deadline, maximum)
        if source != cli.RELEASE_URL:
            cancel.set()
        return data
    download.side_effect = cancel_download
    with pytest.raises(ValueError, match='取消'):
        cli.install_cli(cancel=cancel, deadline=time.monotonic()+5)
    assert (cli.runtime_root()/'active.json').read_bytes() == pointer
    assert Path(old['executable']).is_file()


@pytest.mark.skipif(os.name != 'nt', reason='Windows CLI installation')
def test_update_rejects_downgrade_and_keeps_previous_files(release):
    metadata, _, download = release
    old = install()
    metadata['tag_name'] = 'v0.4.3'
    metadata['assets'][0]['browser_download_url'] = metadata['assets'][0]['browser_download_url'].replace('v0.4.4','v0.4.3')
    download.reset_mock()
    with pytest.raises(ValueError, match='保留既有版本'):
        install()
    assert download.call_count == 1
    assert cli.resolve_executable() == old['executable']


def test_model_query_pages_uses_shared_key_only_in_child_environment(tmp_path, monkeypatch):
    path = tmp_path/'gemini-api.exe'
    path.write_bytes(b'test')
    settings = deepcopy(public_defaults())
    settings['gemini_api_cli']['executable'] = str(path)
    settings['gemini']['api_key'] = 'private-test-key'
    monkeypatch.setenv('GEMINI_ACCESS_TOKEN', 'unrelated-token')
    commands = []
    def run(command, cancel, deadline, *, env):
        commands.append(command)
        assert env['GEMINI_API_KEY'] == 'private-test-key'
        assert 'GEMINI_ACCESS_TOKEN' not in env
        assert 'private-test-key' not in repr(command)
        if '--version' in command:
            return 'gemini-api 0.4.4\nBuilt: test'
        assert command[1:4] == ['--no-interactive', 'models', 'list']
        if '--page-token' not in command:
            return json.dumps({'models':[{'name':'models/lyria-3.5'}], 'nextPageToken':'next'})
        return json.dumps({'models':[{'name':'models/gemini-3.8-flash-tts'}, {'name':'models/lyria-3.5'}]})
    monkeypatch.setattr(cli.CliCatalog, '_run', run)
    result = cli.query_models(settings, cancel=threading.Event(), deadline=time.monotonic()+5)
    assert result['models'] == ('lyria-3.5', 'gemini-3.8-flash-tts')
    assert result['version'] == '0.4.4' and len(commands) == 3
    assert all('generate' not in command and 'music' not in command for command in commands)


@pytest.mark.parametrize('payload', [
    {'models': 'invalid'}, {'models':[{'name':'bad\nname'}]},
    {'models':[None]}, {'models':[]},
])
def test_invalid_models_are_not_accepted(payload, monkeypatch):
    monkeypatch.setattr(cli, 'resolve_executable', lambda _: 'gemini-api.exe')
    monkeypatch.setattr(cli.CliCatalog, '_run', lambda command,*a,**kw:
                        'gemini-api 0.4.4' if '--version' in command else json.dumps(payload))
    settings = deepcopy(public_defaults())
    settings['gemini']['api_key'] = 'test-key'
    with pytest.raises(ValueError, match='格式無效'):
        cli.query_models(settings, cancel=threading.Event(), deadline=time.monotonic()+5)


def test_repeated_model_cursor_does_not_publish_partial_list(monkeypatch):
    monkeypatch.setattr(cli, 'resolve_executable', lambda _: 'gemini-api.exe')
    monkeypatch.setattr(cli.CliCatalog, '_run', lambda command,*a,**kw:
        'gemini-api 0.4.4' if '--version' in command else
        json.dumps({'models':[{'name':'models/lyria-3.5'}], 'nextPageToken':'same'}))
    settings = deepcopy(public_defaults())
    settings['gemini']['api_key'] = 'test-key'
    with pytest.raises(ValueError, match='格式無效'):
        cli.query_models(settings, cancel=threading.Event(), deadline=time.monotonic()+5)


def test_music_settings_round_trip_and_prevent_clip_fallback(tmp_path):
    cfg = Config(str(Path(__file__).resolve().parents[1]/'config.default.json'), str(tmp_path/'private.json'))
    draft = cfg.snapshot()
    assert draft['music']['model'] == 'lyria-3.5'
    draft['gemini_api_cli']['executable'] = 'C:/Programs/gemini-api.exe'
    cfg.apply_snapshot(validate_settings(draft, cfg.snapshot()))
    cfg.load()
    assert cfg.get('gemini_api_cli','executable') == 'C:/Programs/gemini-api.exe'
    assert cfg.get('music','model') == 'lyria-3.5'
    draft['music']['model'] = 'lyria-3-clip-preview'
    with pytest.raises(SettingsError) as error:
        validate_settings(draft,cfg.snapshot())
    assert error.value.path == ('music','model')


def test_missing_key_never_starts_cli_or_sends_request(monkeypatch):
    settings = deepcopy(public_defaults())
    settings['gemini']['api_key_env'] = 'UNSET_TEST_GOOGLE_KEY'
    monkeypatch.delenv('UNSET_TEST_GOOGLE_KEY',raising=False)
    run = Mock(side_effect=AssertionError('CLI should not start'))
    monkeypatch.setattr(cli.CliCatalog,'_run',run)
    from utils.gemini_audio import GeminiAPIError
    with pytest.raises(GeminiAPIError,match='missing_api_key'):
        cli.query_models(settings,cancel=threading.Event(),deadline=time.monotonic()+5)
    run.assert_not_called()


native = pytest.mark.skipif(os.environ.get('AI_GOVERNESS_NATIVE_TESTS') != '1', reason='Opt-in native Tk')


@native
def test_native_model_query_preserves_selection_and_saves_across_pages(tmp_path, monkeypatch):
    import customtkinter as ctk
    from ui.startup import StartupView
    monkeypatch.setattr('ui.gemini_api_settings.resolve_executable', lambda _: 'gemini-api.exe')
    query = Mock(return_value={'models':('lyria-3-clip-preview','lyria-3.5','gemini-3.8-flash'),
                               'version':'0.4.4', 'executable':'gemini-api.exe'})
    monkeypatch.setattr('ui.gemini_api_settings.query_models', query)
    cfg = Config(str(Path(__file__).resolve().parents[1]/'config.default.json'),str(tmp_path/'private.json'))
    root = ctk.CTk()
    root.withdraw()
    view = StartupView(root,cfg.snapshot(),Mock(),catalog=Mock(),on_save=cfg.apply_snapshot)
    try:
        editor = view.gemini_cli_editor
        assert editor.model_field.variable.get() == 'lyria-3.5'
        assert editor.model_field.widget.cget('values') == ['lyria-3.5']
        editor.path_field.variable.set('C:/Programs/gemini-api.exe')
        editor.query_button.invoke()
        view.gemini_cli_controller.thread.join(timeout=2)
        until=time.monotonic()+.25
        while time.monotonic()<until:
            root.update()
            time.sleep(.01)
        assert query.call_count == 1
        assert 'lyria-3.5' in editor.models.get('1.0','end')
        assert editor.model_field.variable.get() == 'lyria-3.5'
        view.navigate(3)
        view.navigate(0)
        assert view.gemini_cli_editor.path_field.variable.get() == 'C:/Programs/gemini-api.exe'
        view.save_draft()
        cfg.load()
        assert cfg.get('music','model') == 'lyria-3.5'
        assert cfg.get('gemini_api_cli','executable') == 'C:/Programs/gemini-api.exe'
    finally:
        view.destroy()
        for job in root.tk.call('after','info'):
            root.after_cancel(job)
        root.destroy()


@native
def test_native_key_change_cancels_and_discards_inflight_catalog(monkeypatch):
    import customtkinter as ctk
    from ui.startup import StartupView
    monkeypatch.setattr('ui.gemini_api_settings.resolve_executable',lambda _: 'gemini-api.exe')
    started = threading.Event()
    def query(settings, *, cancel, **kwargs):
        started.set()
        cancel.wait(2)
        return {'models':('lyria-3.5',),'version':'old-key-result','executable':'gemini-api.exe'}
    monkeypatch.setattr('ui.gemini_api_settings.query_models',query)
    root=ctk.CTk()
    root.withdraw()
    view=StartupView(root,deepcopy(public_defaults()),Mock(),catalog=Mock())
    try:
        editor=view.gemini_cli_editor
        editor.start()
        assert started.wait(1)
        view._google_key_changed('new-key')
        view.gemini_cli_controller.thread.join(timeout=2)
        editor.poll()
        assert 'old-key-result' not in editor.status.cget('text')
        assert not view.gemini_cli_state
        assert view.settings['gemini']['api_key']=='new-key'
    finally:
        view.destroy()
        for job in root.tk.call('after','info'):
            root.after_cancel(job)
        root.destroy()


@native
def test_native_update_activates_managed_path_without_changing_music_model(monkeypatch):
    import customtkinter as ctk
    from ui.startup import StartupView
    monkeypatch.setattr('ui.gemini_api_settings.resolve_executable',lambda _: 'gemini-api.exe')
    update=Mock(return_value={'version':'v0.4.5','executable':'managed/gemini-api.exe','updated':True})
    monkeypatch.setattr('ui.gemini_api_settings.install_cli',update)
    settings=deepcopy(public_defaults())
    settings['gemini_api_cli']['executable']='old/gemini-api.exe'
    root=ctk.CTk()
    root.withdraw()
    view=StartupView(root,settings,Mock(),catalog=Mock())
    try:
        editor=view.gemini_cli_editor
        editor.update_button.invoke()
        view.gemini_cli_controller.thread.join(timeout=2)
        until=time.monotonic()+.25
        while time.monotonic()<until:
            root.update()
            time.sleep(.01)
        assert update.call_count==1
        assert editor.path_field.variable.get()==''
        assert editor.model_field.variable.get()=='lyria-3.5'
        assert view.collect()
        assert view.settings['gemini_api_cli']['executable']==''
        editor.path_field.variable.set('different/gemini-api.exe')
        assert not view.gemini_cli_state
        assert '重新查詢' in editor.status.cget('text')
    finally:
        view.destroy()
        for job in root.tk.call('after','info'):
            root.after_cancel(job)
        root.destroy()
