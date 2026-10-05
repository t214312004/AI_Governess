"""Boundary regressions found during the production UI follow-up audit."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import json
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm.acp_stdio_client import ACPStdioClient
from llm.codex_cli_client import CodexCLIClient
from llm.model_catalog import CliCatalog
from llm.opencode_cli_client import OpenCodeCLIClient


def test_rolling_wall_clock_back_keeps_charging_html(tmp_path):
    from core.html_usage import HtmlUsageBudget, TAIPEI
    stamp = [0.0]
    wall = [datetime(2026, 10, 5, 12, tzinfo=TAIPEI)]
    budget = HtmlUsageBudget(tmp_path, 30, clock=lambda: stamp[0], now=lambda: wall[0])
    budget.tick(True)
    stamp[0] = 10
    budget.tick(True)
    wall[0] -= timedelta(days=1)
    stamp[0] = 35
    budget.tick(False)
    assert budget.remaining == 0
    assert json.loads(budget.path.read_text())['day'] == '2026-10-05'


@pytest.mark.parametrize('changes', [{'day': '20261005'}, {'day': '2026-W41-1'},
                                   {'version': 2}, {'version': True}])
def test_noncanonical_or_unknown_quota_record_is_blocked(tmp_path, changes):
    from core.html_usage import HtmlUsageBudget
    record = dict(version=1, day='2026-10-05', used_seconds=0, **{})
    record.update(changes)
    (tmp_path / 'html-usage.json').write_text(json.dumps(record))
    with pytest.raises(ValueError):
        HtmlUsageBudget(tmp_path)


def test_claude_catalog_uses_print_mode_and_only_initialization():
    catalog = CliCatalog(lambda: {'llm': {'claude_code': {}}})
    response = {'type': 'control_response', 'response': {'response': {'models': [
        {'value': 'from-cli', 'supportedEffortLevels': ['from-cli-effort']}]}}}
    with patch.object(catalog, '_executable', return_value='claude.exe'), \
            patch.object(catalog, '_run', return_value='0\n' + json.dumps(response)) as run:
        models = catalog.query('claude_code', False, cancel=threading.Event())
    command = run.call_args.args[0]
    assert '-p' in command and command[command.index('--input-format') + 1] == 'stream-json'
    assert run.call_args.kwargs['request']['request']['subtype'] == 'initialize'
    assert models[0].id == 'from-cli' and models[0].efforts == ('from-cli-effort',)


def test_catalog_does_not_reuse_effort_after_model_removes_capabilities():
    client = MagicMock()
    client.ensure_ready = AsyncMock()
    client.aclose = AsyncMock()
    options = [{'id': 'model', 'options': [{'value': 'first'}, {'value': 'second'}]},
               {'id': 'effort', 'options': [{'value': 'initial-effort'}]}]
    client._session_config_options = options
    client._find_config_option = ACPStdioClient._find_config_option
    client._config_option_values = ACPStdioClient._config_option_values
    async def change(current, category, value):
        if value == 'first':
            client._session_config_options = [options[0]]
        else:
            assert current == [options[0]]
            client._session_config_options = []
    client._set_config_option = AsyncMock(side_effect=change)
    with patch('llm.client_factory.create_llm_client', return_value=client):
        models = asyncio.run(CliCatalog(lambda: {})._query_protocol(
            'opencode_cli', {'llm': {'opencode_cli': {}}}, threading.Event(), time.monotonic()+3))
    assert [model.efforts for model in models] == [(), ()]
    client.aclose.assert_awaited_once()


def test_acp_grouped_models_use_advertised_option_id(tmp_path):
    client = OpenCodeCLIClient(project_dir=str(tmp_path), model='second')
    client.session_id = 'session'
    options = [{'id': 'provider-model', 'category': 'model', 'options': [
        {'group': 'provider', 'name': 'Provider', 'options': [
            {'value': 'first'}, {'value': 'second'}]}]}]
    client._send_request = AsyncMock(return_value={'result': {'configOptions': options}})
    asyncio.run(client._apply_session_config_options(options))
    assert ACPStdioClient._config_option_values(options[0]) == ['first', 'second']
    assert client._send_request.call_args.args[1]['configId'] == 'provider-model'


def test_acp_refresh_uses_new_session_and_model_capabilities(tmp_path):
    client = OpenCodeCLIClient(project_dir=str(tmp_path), model='chosen', mode='build',
                               reasoning_effort='deep')
    client.session_id = 'old'
    client.process = MagicMock(returncode=None)
    client._ready_event.set()
    client._session_config_options = [{'id': 'obsolete', 'category': 'thought_level',
                                       'options': [{'value': 'shallow'}]}]
    initial = [{'id': 'model', 'options': [{'value': 'chosen'}]},
               {'id': 'mode', 'options': [{'value': 'old-mode'}]}]
    changed = [{'id': 'model', 'options': [{'value': 'chosen'}]},
               {'id': 'mode', 'options': [{'value': 'build'}]},
               {'id': 'new-effort', 'category': 'thought_level', 'options': [{'value': 'deep'}]}]
    async def response(method, params, **kwargs):
        if method == 'session/new':
            return {'result': {'sessionId': 'new', 'configOptions': deepcopy(initial)}}
        assert params['sessionId'] == 'new'
        return {'result': {'configOptions': deepcopy(changed)}}
    client._send_request = AsyncMock(side_effect=response)
    assert asyncio.run(client.refresh_session())
    requests = client._send_request.call_args_list
    assert [c.args[1].get('configId') for c in requests] == [None, 'model', 'mode', 'new-effort']
    assert client._session_config_options == changed


def test_acp_capability_notification_updates_only_current_session(tmp_path):
    client = OpenCodeCLIClient(project_dir=str(tmp_path))
    client.session_id = 'current'
    options = [{'id': 'model', 'options': [{'value': 'from-agent'}]}]
    update = {'sessionUpdate': 'config_option_update', 'configOptions': options}
    client._handle_session_update({'sessionId': 'other', 'update': update})
    assert client._session_config_options is None
    client._handle_session_update({'sessionId': 'current', 'update': update})
    assert client._session_config_options == options


@pytest.mark.parametrize('backend', ['opencode_cli', 'grok_cli'])
def test_catalog_replaces_private_context_paths_with_empty_workspace(backend, tmp_path):
    client = MagicMock()
    client.ensure_ready = AsyncMock()
    client.aclose = AsyncMock()
    options = [{'id': 'model', 'options': [{'value': 'queried'}]}]
    client._session_config_options = options
    client._find_config_option = ACPStdioClient._find_config_option
    client._config_option_values = ACPStdioClient._config_option_values
    client._set_config_option = AsyncMock()
    settings = {'llm': {backend: {'required_context_files': [str(tmp_path / 'private-rules.md')],
                                 'instruction_files': [str(tmp_path / 'private-memory.md')]}}}
    def factory(name, **kwargs):
        from pathlib import Path
        assert name == backend and not kwargs['load_private_context']
        assert kwargs['required_context_files'] == ['AGENTS.md']
        assert kwargs['instruction_files'] == ['MEMORY.md']
        workspace = Path(kwargs['project_dir'])
        assert (workspace / 'AGENTS.md').read_text() == ''
        assert (workspace / 'MEMORY.md').read_text() == ''
        return client
    with patch('llm.client_factory.create_llm_client', side_effect=factory):
        models = asyncio.run(CliCatalog(lambda: settings)._query_protocol(
            backend, settings, threading.Event(), time.monotonic()+3))
    assert [m.id for m in models] == ['queried']
    client.aclose.assert_awaited_once()


@pytest.mark.parametrize('client_type', [OpenCodeCLIClient, CodexCLIClient])
def test_owned_client_shutdown_never_falls_back_to_pid_taskkill(client_type, tmp_path):
    client = client_type(project_dir=str(tmp_path))
    client.process = MagicMock(returncode=None)
    client.process.wait = AsyncMock(return_value=0)
    process = client.process
    owner = MagicMock()
    client._process_job = owner
    client.cancel = AsyncMock()
    with patch('asyncio.create_subprocess_exec', new_callable=AsyncMock) as spawn:
        asyncio.run(client.aclose())
    spawn.assert_not_awaited()
    process.wait.assert_awaited_once()
    process._transport.close.assert_called_once()
    assert client._process_job is None


def test_emergency_shutdown_uses_owned_tree_even_after_parent_exit():
    from core.assistant import VoiceAssistant
    from types import SimpleNamespace
    owner = MagicMock()
    client = SimpleNamespace(_process_job=owner, process=MagicMock(returncode=0))
    assistant = VoiceAssistant.__new__(VoiceAssistant)
    with patch('core.assistant.subprocess.run') as run:
        assert assistant._force_terminate_llm_process(client, reason='test')
    owner.close.assert_called_once()
    run.assert_not_called()


@pytest.mark.parametrize('message', ['Pipeline runtime is busy: active_turn',
                                     'Pipeline Turn is no longer active.'])
def test_text_voice_race_is_busy_instead_of_losing_queued_message(message):
    from core.assistant import VoiceAssistant
    assistant = VoiceAssistant.__new__(VoiceAssistant)
    assistant.async_loop = object()
    assistant.llm_client = object()
    assistant.can_accept_text_message = MagicMock(return_value=True)
    assistant._build_utterance_id = MagicMock(return_value='request')
    assistant._mark_user_interaction = MagicMock()
    assistant._should_skip_llm_request = MagicMock(return_value=False)
    assistant._clear_interrupt_signal = MagicMock()
    assistant._execute_text_llm_request = AsyncMock()
    def competing_turn(coro, *args, **kwargs):
        coro.close()
        raise RuntimeError(message)
    assistant._submit_request = competing_turn
    assert assistant.send_text_message('retain this') == (False, 'busy')


def make_ui():
    from ui.session_window import VoiceAssistantUI
    ui = VoiceAssistantUI.__new__(VoiceAssistantUI)
    ui._closing_event = threading.Event()
    ui.after = MagicMock(return_value='timer')
    ui.after_cancel = MagicMock()
    return ui


@pytest.mark.parametrize('content_type', ['markdown', 'html'])
def test_tool_visibility_changes_reach_session_and_keep_markdown_widget(tmp_path, content_type):
    from core.whiteboard_manager import WhiteboardManager
    ui = make_ui()
    manager = WhiteboardManager(tmp_path)
    if content_type == 'html':
        page = manager.apps_root / 'visibility.html'
        page.write_text('<!doctype html><h1>Visibility</h1>', encoding='utf-8')
        manager.show_html({'html_path': str(page)})
    else:
        manager.show_markdown({'markdown': '# Preserve document'})
    ui.assistant = MagicMock(whiteboard_manager=manager)
    ui._whiteboard_rendered_content_id = None
    ui._whiteboard_current_state = None
    ui._whiteboard_active_mtime_ns = None
    ui.board_visible = False
    ui._account_budget = MagicMock()
    ui._schedule_whiteboard_poll = MagicMock()
    ui._clear_whiteboard_body = MagicMock()
    ui._cancel_html_status_check = MagicMock()
    ui._release_whiteboard_keyboard_capture = MagicMock()
    ui._set_whiteboard_input_monitor_paused = MagicMock()
    ui._sync_whiteboard_keyboard_guard = MagicMock()
    ui._html_allowed = MagicMock(return_value=True)
    ui._render_whiteboard_html = MagicMock()
    ui._render_whiteboard_markdown = MagicMock()
    for name in ('board', 'restore_button', 'board_title', 'board_sound', 'board_reload',
                 'quota_row', 'html_whiteboard_renderer'):
        setattr(ui, name, MagicMock())

    ui._poll_whiteboard_state()
    assert ui.board_visible
    content_id = manager.get_active()['content_id']
    manager.hide(content_id)
    ui._poll_whiteboard_state()
    assert not ui.board_visible and manager.status()['hidden']
    ui._set_whiteboard_input_monitor_paused.assert_called_with(False)
    ui._release_whiteboard_keyboard_capture.assert_called()
    if content_type == 'html':
        ui.html_whiteboard_renderer.stop.assert_called()
    manager.restore(content_id)
    ui._poll_whiteboard_state()
    assert ui.board_visible and not manager.status()['hidden']
    ui._set_whiteboard_input_monitor_paused.assert_called_with(True)
    if content_type == 'markdown':
        ui._render_whiteboard_markdown.assert_called_once()
        ui._clear_whiteboard_body.assert_not_called()
    else:
        assert ui._render_whiteboard_html.call_count == 2


def test_session_polling_recovers_after_transient_callback_failure():
    ui = make_ui()
    ui._tick_session = MagicMock(side_effect=RuntimeError('transient'))
    ui.tick()
    ui.after.assert_called_once_with(250, ui.tick)
    assert ui._tick_job == 'timer'


def test_backend_submission_exception_keeps_fifo_for_retry():
    from collections import deque
    ui = make_ui()
    ui.pending = deque([(1, 'first'), (2, 'second')])
    ui.assistant = MagicMock()
    ui.assistant.audio_player.is_playing = False
    ui.assistant.can_accept_text_message.return_value = True
    ui.assistant.send_text_message.side_effect = [RuntimeError('backend stopped'), (True, None)]
    ui._refresh_pending = MagicMock()
    ui._add_bubble_logic = MagicMock()
    ui.notify = MagicMock()
    ui.dispatch()
    assert list(ui.pending) == [(1, 'first'), (2, 'second')]
    ui.dispatch()
    assert list(ui.pending) == [(2, 'second')]
    assert [c.args[0] for c in ui.assistant.send_text_message.call_args_list] == ['first', 'first']


def test_html_status_does_not_steal_composer_focus_or_check_hidden_or_stale_host():
    ui = make_ui()
    ui._html_status_job = 'old-timer'
    ui.board_visible = True
    ui._whiteboard_current_state = {'content_type': 'html', 'content_id': 'board'}
    ui.html_whiteboard_renderer = MagicMock(_generation=3, last_error=None, is_attached=True)
    ui._composer_focused = True
    ui._render_whiteboard_error = MagicMock()
    ui._check_whiteboard_html_status('board', 0, 3)
    ui.html_whiteboard_renderer.focus.assert_not_called()
    ui.board_visible = False
    ui._composer_focused = False
    ui.html_whiteboard_renderer.last_error = 'stale error'
    ui._check_whiteboard_html_status('board', 160, 3)
    ui.board_visible = True
    ui._check_whiteboard_html_status('board', 160, 2)
    ui._render_whiteboard_error.assert_not_called()
    ui.after.assert_not_called()


def test_quota_corrupted_after_startup_is_still_blocked(tmp_path):
    from core.html_usage import HtmlUsageBudget
    ui = make_ui()
    ui.budget = HtmlUsageBudget(tmp_path)
    ui._quota_failed = False
    ui.budget.path.write_text('not JSON', encoding='utf-8')
    assert not ui._html_allowed() and ui._quota_failed
