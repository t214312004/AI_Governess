"""Startup settings shared by the editor and production launch path."""
from copy import deepcopy
from dataclasses import dataclass
import json
import math

BACKENDS = ('codex_cli', 'claude_code', 'opencode_cli', 'grok_cli', 'antigravity_cli')
EFFORT_KEYS = {'antigravity_cli': 'effort',
               'claude_code': 'effort'}


@dataclass(frozen=True)
class SessionConfig:
    backend: str
    model: str
    effort: str
    voice_input: bool = True
    voice_output: bool = True
    html_minutes: int = 30
    chat_font: int = 21

    def __post_init__(self):
        if self.backend not in BACKENDS or not self.model.strip():
            raise ValueError('請查詢並選擇模型')
        if type(self.html_minutes) is not int or not 0 <= self.html_minutes <= 1440:
            raise ValueError('HTML 分鐘必須介於 0–1440')
        if type(self.chat_font) is not int or not 16 <= self.chat_font <= 32:
            raise ValueError('對話字級必須介於 16–32')


def assign(draft, path, value):
    node = draft
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def parse_field(raw, original):
    if type(original) is bool:
        if type(raw) is not bool:
            raise ValueError('必須是布林值')
        return raw
    if type(original) is int:
        return int(raw)
    if type(original) is float:
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError('必須是有限數值')
        return value
    if isinstance(original, list):
        value = json.loads(raw)
        if not isinstance(value, list):
            raise ValueError('請輸入 JSON 清單')
        return value
    if original is None:
        return None if not raw.strip() else json.loads(raw)
    return str(raw)


def validate_settings(settings, defaults):
    """Preserve unknown local keys; reject incompatible edits before construction."""
    def check(current, expected, path=()):
        name = '.'.join(path)
        if isinstance(expected, dict):
            if not isinstance(current, dict) or set(current) != set(expected):
                raise ValueError(f'{name}：設定結構不符')
            for key, value in expected.items():
                check(current[key], value, (*path, key))
        elif expected is not None and type(current) is not type(expected):
            raise ValueError(f'{name}：型別不符')
        if type(current) in (int, float) and not math.isfinite(current):
            raise ValueError(f'{name}：數值無效')
        if type(current) in (int, float):
            positive = path[-1] in ('input_sample_rate', 'output_sample_rate',
                'input_block_size', 'output_block_size', 'animation_interval_ms',
                'tts_queue_chunks', 'playback_queue_chunks') or 'timeout_seconds' in path[-1]
            if positive and current <= 0:
                raise ValueError(f'{name}：必須大於 0')
    check(settings, defaults)
    for group, key in (('vad', 'threshold'), ('speaker_recognition', 'threshold'),
                       ('whiteboard', 'html_audio_duck_volume')):
        if not 0 <= settings[group][key] <= 1:
            raise ValueError(f'{group}.{key}：必須介於 0–1')
    pipeline = settings['pipeline_v2_5']
    if pipeline['tts_chunk_min_chars'] > pipeline['tts_chunk_max_chars']:
        raise ValueError('TTS 最小長度不得大於最大長度')
    for path, allowed in ((('whisper', 'backend'), ('local', 'groq')),
                          (('tts', 'backend'), ('edge', 'bluemagpie'))):
        if settings[path[0]][path[1]] not in allowed:
            raise ValueError(f'{".".join(path)}：不支援的服務')
    json.dumps(settings, allow_nan=False)
    return deepcopy(settings)


def session_snapshot(settings, cfg):
    snapshot = deepcopy(settings)
    snapshot['llm']['active_backend'] = cfg.backend
    backend = snapshot['llm'][cfg.backend]
    backend['model'] = cfg.model
    backend[EFFORT_KEYS.get(cfg.backend, 'reasoning_effort')] = cfg.effort
    snapshot['interaction'] = dict(snapshot.get('interaction', {}),
        voice_input=cfg.voice_input, voice_output=cfg.voice_output)
    snapshot['whiteboard']['html_daily_minutes'] = cfg.html_minutes
    snapshot['ui']['chat_font_size'] = cfg.chat_font
    snapshot['ui']['fullscreen_exit_shortcuts'] = ['ALT+F4']
    snapshot['ui']['fullscreen_enter_shortcuts'] = []
    return snapshot
