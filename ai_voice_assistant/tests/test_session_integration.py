"""Production integration regressions. No live household config or LLM turns."""
import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
import json
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from config import Config
from core.audio_player import AudioPlayer
from core.html_usage import HtmlUsageBudget
from core.session_settings import SessionConfig, parse_field, session_snapshot
from core.whiteboard_manager import WhiteboardManager
from llm.model_catalog import CliCatalog, advertised_choices, antigravity_models


def test_startup_snapshot_preserves_all_local_values(tmp_path):
    defaults = tmp_path / 'default.json'
    local = tmp_path / 'local.json'
    defaults.write_text(json.dumps({'nested': {'value': 1}, 'llm': {'active_backend': 'a'}}))
    local.write_text(json.dumps({'nested': {'value': 7}, 'unknown': {'custom': 'local'}}))
    cfg = Config(str(defaults), str(local))
    draft = cfg.snapshot()
    assert draft['nested']['value'] == 7 and draft['unknown']['custom'] == 'local'
    draft['nested']['value'] = 8
    assert cfg.get('nested', 'value') == 7
    cfg.apply_snapshot(draft)
    assert Config(str(defaults), str(local)).snapshot() == draft


def test_startup_write_failure_keeps_file_and_memory(tmp_path):
    local = tmp_path / 'local.json'
    local.write_text('{"a": 1}')
    cfg = Config(str(tmp_path / 'absent'), str(local))
    with patch('config.os.replace', side_effect=OSError('disk full')):
        with pytest.raises(OSError):
            cfg.apply_snapshot({'a': 2})
    assert cfg.snapshot() == {'a': 1}
    assert local.read_text() == '{"a": 1}'


def test_failed_launch_rollback_removes_new_keys(tmp_path):
    local = tmp_path / 'local.json'
    local.write_text('{"group": {"a": 1}}')
    cfg = Config(str(tmp_path / 'absent'), str(local))
    old = cfg.snapshot()
    cfg.apply_snapshot({'group': {'a': 2, 'new': 'x'}, 'new_group': 3})
    cfg.apply_snapshot(old)
    assert Config(str(tmp_path / 'absent'), str(local)).snapshot() == old


@pytest.mark.parametrize('backend,key', [('codex_cli', 'reasoning_effort'),
    ('grok_cli', 'reasoning_effort'), ('claude_code', 'effort'),
    ('antigravity_cli', 'effort'), ('opencode_cli', 'reasoning_effort')])
def test_backend_selections_reach_correct_config_key(backend, key):
    settings = {'llm': {'active_backend': 'old', backend: {'project_dir': 'private-test'}},
                'whiteboard': {}, 'ui': {}, 'custom': {'unchanged': 11}}
    result = session_snapshot(settings, SessionConfig(backend, 'queried-model', 'queried-effort', False, True, 17, 24))
    assert result['llm'][backend]['model'] == 'queried-model'
    assert result['llm'][backend][key] == 'queried-effort'
    assert result['interaction'] == {'voice_input': False, 'voice_output': True}
    assert result['custom'] == settings['custom']
    assert result['ui']['fullscreen_exit_shortcuts'] == ['ALT+F4']


def test_nullable_and_structured_settings_keep_types():
    assert parse_field('', None) is None
    assert parse_field('[-2, {"x": true}]', []) == [-2, {'x': True}]
    assert parse_field('-7', None) == -7
    with pytest.raises(ValueError):
        parse_field('nan', 1.0)


def test_daily_quota_visible_pause_restart_and_tool_block(tmp_path):
    wall = [datetime(2026, 10, 4, 12, tzinfo=timezone(timedelta(hours=8)))]
    stamp = [0.0]
    budget = HtmlUsageBudget(tmp_path, 4, clock=lambda: stamp[0], now=lambda: wall[0])
    budget.tick(True)
    stamp[0] = 2
    budget.tick(False)
    stamp[0] = 60
    budget.tick(False)
    assert budget.remaining == 2
    restarted = HtmlUsageBudget(tmp_path, 4, clock=lambda: stamp[0], now=lambda: wall[0])
    assert restarted.remaining == 2
    restarted.tick(True)
    stamp[0] += 3
    restarted.tick(False)
    assert restarted.remaining == 0
    # The backend tool uses the same durable quota, independent of UI controls.
    manager = WhiteboardManager(tmp_path, state_dir=tmp_path, html_daily_minutes=0)
    assert manager.show_html({})['status'] == 'blocked'
    assert manager.show_markdown({'markdown': '# Still allowed'})['status'] == 'shown'


def test_quota_merges_independent_owners_and_rolls_at_midnight(tmp_path):
    wall = [datetime(2026, 10, 4, 23, 59, 59, tzinfo=timezone(timedelta(hours=8)))]
    stamp = [0.0]
    kwargs = dict(clock=lambda: stamp[0], now=lambda: wall[0])
    a, b = HtmlUsageBudget(tmp_path, 30, **kwargs), HtmlUsageBudget(tmp_path, 30, **kwargs)
    a.tick(True)
    b.tick(True)
    stamp[0] = .5
    a.tick(False)
    b.tick(False)
    assert a.refresh() == 29
    a.tick(True)
    wall[0] += timedelta(seconds=2)
    stamp[0] += 2
    a.tick(False)
    assert a.remaining == 29  # Only one second belongs to the new day.
    wall[0] -= timedelta(days=1)
    assert a.refresh() == 29


def test_corrupt_quota_fails_closed(tmp_path):
    (tmp_path / 'html-usage.json').write_text('{"day": "2026-10-04", "used_seconds": -1}')
    with pytest.raises(ValueError):
        HtmlUsageBudget(tmp_path)
    manager = WhiteboardManager(tmp_path, state_dir=tmp_path)
    assert manager.show_html({})['status'] == 'blocked'


def test_muting_keeps_generation_and_drops_audio():
    player = AudioPlayer()
    player.set_response_generation(7)
    player.play(np.ones(100, dtype=np.int16), response_generation=7)
    player.set_muted(True)
    assert player.response_generation == 7
    assert not player.is_playing
    assert not player.play(np.ones(100, dtype=np.int16), response_generation=7)
    output = np.ones((20, 1), dtype=np.int16)
    player._output_callback(output, 20, None, None)
    assert not output.any()


def test_output_callback_drops_audio_crossing_a_mute_cycle():
    player = AudioPlayer()
    player.start = MagicMock()
    payload = np.ones(100, dtype=np.int16)
    def race():
        player.set_muted(True)
        player.set_muted(False)
        return payload
    player.playback_queue.get_nowait = MagicMock(side_effect=race)
    # set_muted drains with get_nowait; keep that operation separate from
    # the callback's simulated dequeue so the test cannot recursively mute.
    original = player.set_muted
    def toggle(muted):
        with patch.object(player.playback_queue, 'get_nowait', side_effect=__import__('queue').Empty):
            original(muted)
    player.set_muted = toggle
    output = np.ones((20, 1), dtype=np.int16)
    player._output_callback(output, 20, None, None)
    assert not output.any() and player._residual_data is None


def test_startup_failure_reenables_retry_even_if_cleanup_fails():
    from types import SimpleNamespace
    from ui.startup_window import StartupWindow
    ui = StartupWindow.__new__(StartupWindow)
    ui.preparing = ui.cancelled = False
    ui.events = __import__('queue').SimpleQueue()
    ui.view = MagicMock()
    ui.view.nav_buttons = [MagicMock()]
    ui.after = MagicMock()
    assistant = MagicMock()
    assistant.prepare_for_gui.side_effect = RuntimeError('backend not ready')
    assistant.shutdown_prepared_resources.side_effect = RuntimeError('cleanup failed')
    ui.factory = MagicMock(return_value=assistant)
    cfg = MagicMock()
    cfg.snapshot.return_value = {'previous': True}
    def immediate_thread(*, target, **kwargs):
        return SimpleNamespace(start=target)
    with patch('ui.startup_window.config', cfg), patch('ui.startup_window.threading.Thread', side_effect=immediate_thread):
        ui._prepare(None, {'draft': True})
    assert cfg.apply_snapshot.call_args_list[-1].args == ({'previous': True},)
    ui._poll()
    assert not ui.preparing
    assert [c.args[0] for c in ui.view.set_preparing.call_args_list] == [True, False]


def make_session_ui():
    from ui.session_window import VoiceAssistantUI
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui.pending = deque([(1, 'first'), (2, 'second')])
    ui.assistant = MagicMock()
    ui.assistant.audio_player.is_playing = True
    ui.assistant.can_accept_text_message.return_value = True
    ui.assistant.send_text_message.return_value = (True, None)
    ui._add_bubble_logic = MagicMock()
    ui._refresh_pending = MagicMock()
    ui.notify = MagicMock()
    return ui


def test_fifo_waits_for_playback_and_preserves_busy_rejection():
    ui = make_session_ui()
    ui.dispatch()
    ui.assistant.send_text_message.assert_not_called()
    ui.assistant.audio_player.is_playing = False
    ui.assistant.send_text_message.return_value = (False, 'busy')
    ui.dispatch()
    assert list(ui.pending) == [(1, 'first'), (2, 'second')]
    ui.assistant.send_text_message.return_value = (True, None)
    ui.dispatch()
    ui.dispatch()
    assert [call.args[0] for call in ui.assistant.send_text_message.call_args_list[-2:]] == ['first', 'second']


def test_fixed_text_icons_cannot_enable_audio():
    ui = make_session_ui()
    ui.session = SessionConfig('codex_cli', 'from-cli', '', False, False)
    ui.toggle_mic()
    ui.toggle_speaker()
    ui.assistant.set_microphone_muted.assert_not_called()
    ui.assistant.set_output_muted.assert_not_called()


def test_cli_choices_are_advertised_and_query_cancellation_is_bounded():
    assert advertised_choices('--effort string  Effort level (one|two)', '--effort') == ('one', 'two')
    assert advertised_choices('--effort string', '--effort') == ()
    import sys, time
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ValueError, match='取消'):
        CliCatalog._run([sys.executable, '-c', 'import time; time.sleep(30)'], cancel, time.monotonic()+2)


def test_cancelled_catalog_query_does_not_start_subprocess():
    import time
    cancel = threading.Event()
    cancel.set()
    with patch('llm.model_catalog.subprocess.Popen') as spawn:
        with pytest.raises(ValueError, match='取消'):
            CliCatalog._run(['unused.exe'], cancel, time.monotonic() + 2)
    spawn.assert_not_called()


def test_antigravity_effort_variants_cannot_offer_conflicting_levels():
    models = antigravity_models('Fetching models...\nmodel-high\tModel (High)\nmodel-low\tModel (Low)\nplain\tPlain',
                               ('low', 'medium', 'high'))
    assert [m.efforts for m in models] == [('high',), ('low',), ()]


def test_opencode_thought_level_is_separate_from_operating_mode():
    from llm.opencode_cli_client import OpenCodeCLIClient
    client = OpenCodeCLIClient(mode='build', reasoning_effort='deep')
    client.session_id = 'session'
    options = [{'id': 'mode', 'options': [{'value': 'build'}]},
               {'id': 'thinking', 'category': 'thought_level', 'options': [{'value': 'deep'}]}]
    client._send_request = AsyncMock(return_value={'result': {}})
    asyncio.run(client._apply_session_config_options(options))
    assert [c.args[1]['configId'] for c in client._send_request.call_args_list] == ['mode', 'thinking']


def test_text_voice_output_uses_existing_streaming_pipeline():
    from core.assistant import VoiceAssistant
    assistant = VoiceAssistant.__new__(VoiceAssistant)
    assistant.voice_output_enabled = True
    assistant.audio_player = MagicMock()
    assistant._update_state = MagicMock()
    assistant._consume_pending_interrupt_notice = MagicMock(return_value='notice')
    assistant._build_llm_text = MagicMock(return_value='enriched')
    assistant._execute_llm_request = AsyncMock()
    asyncio.run(assistant._execute_text_llm_request('typed', llm_client='client', request_id='id'))
    assistant._execute_llm_request.assert_awaited_once_with('enriched', llm_client='client', request_id='id')
    assistant.audio_player.interrupt.assert_not_called()  # Preserve the turn's audio generation.


def test_output_mute_interrupts_only_audio_and_stays_cancelled_after_unmute():
    from core.assistant import VoiceAssistant, _OutputInterruptSignal
    assistant = VoiceAssistant.__new__(VoiceAssistant)
    assistant.voice_output_enabled = True
    assistant.output_muted = False
    assistant._output_mute_epoch = 0
    assistant.audio_player = MagicMock()
    backend_cancel = asyncio.Event()
    signal = _OutputInterruptSignal(assistant, backend_cancel)
    assert not signal.is_set()
    assistant.set_output_muted(True)
    assistant.set_output_muted(False)
    assert signal.is_set() and not backend_cancel.is_set()


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows process ownership')
def test_cli_job_owns_and_closes_descendant_processes():
    from llm.process_owner import create_owned_subprocess
    import sys
    async def check():
        code = 'import subprocess,sys,time; child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); print(child.pid,flush=True); time.sleep(60)'
        process, job = await create_owned_subprocess(sys.executable, '-c', code,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=0x08000000)
        try:
            child = int(await asyncio.wait_for(process.stdout.readline(), timeout=5))
            assert job.owns(child)
            job.close()
            await asyncio.wait_for(process.wait(), timeout=5)
            assert process.returncode is not None
        finally:
            job.close()
    asyncio.run(check())
