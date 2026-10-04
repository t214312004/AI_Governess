"""Validate the editable draft before publishing the immutable session snapshot.

This covers type, numeric safety and constraints consumed by this preview.
Backend/audio-specific compatibility remains the real adapters' responsibility.
"""
from copy import deepcopy
import math
from domain import finite_number


def assign(draft, path, value):
    target = draft
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def parse_field(raw, original):
    if isinstance(original, bool):
        if type(raw) is not bool:
            raise ValueError('必須是布林值')
        return raw
    if isinstance(original, int):
        return int(raw)
    if isinstance(original, float):
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError('必須是有限數值')
        return value
    if isinstance(original, list):
        return [part.strip() for part in raw.split(';') if part.strip()]
    if original is None:
        return None if not raw.strip() else int(raw)
    return str(raw)


def validate_settings(settings, defaults):
    def check(current, expected, path=()):
        name = '.'.join(path)
        if isinstance(expected, dict):
            if not isinstance(current, dict) or set(current) != set(expected):
                raise ValueError(f'{name}：設定結構不符')
            for key, value in expected.items():
                check(current[key], value, (*path, key))
            return
        if expected is None:
            if current is not None and (type(current) is not int or current < 0):
                raise ValueError(f'{name}：必須是非負整數或空白')
        elif type(current) is not type(expected):
            raise ValueError(f'{name}：型別不符')
        if type(current) in (int, float):
            if not finite_number(current):
                raise ValueError(f'{name}：數值無效')
            if type(current) is int and abs(current) > 2147483647:
                raise ValueError(f'{name}：整數超出支援範圍')
            # Negative offsets/log probabilities/seeds have explicit semantics.
            allow_negative = path[-1] in ('animation_foreground_y_offset_px', 'avg_logprob_threshold')
            if current < 0 and not allow_negative:
                raise ValueError(f'{name}：不得為負值')
            requires_positive = any(part in path[-1] for part in ('sample_rate', 'block_size', 'interval', 'timeout', 'queue_chunks', 'max_'))
            if requires_positive and current <= 0:
                raise ValueError(f'{name}：必須大於 0')
        if isinstance(current, list) and any(not isinstance(item, str) or not item for item in current):
            raise ValueError(f'{name}：清單項目必須是文字')
    check(settings, defaults)
    for group, keys in (
        ('vad', ('threshold', 'fallback_silence_rms_threshold')),
        ('speaker_recognition', ('threshold', 'min_score_margin')),
        ('whiteboard', ('html_audio_duck_volume',)),
    ):
        for key in keys:
            if not 0 <= settings[group][key] <= 1:
                raise ValueError(f'{group}.{key}：必須介於 0–1')
    if settings['pipeline_v2_5']['tts_chunk_min_chars'] > settings['pipeline_v2_5']['tts_chunk_max_chars']:
        raise ValueError('TTS 最小長度不得大於最大長度')
    return deepcopy(settings)


def session_snapshot(settings, cfg):
    snapshot = deepcopy(settings)
    snapshot['llm']['active_backend'] = cfg.backend
    backend = snapshot['llm'][cfg.backend]
    # Include capability selections even when the public default lacks a key.
    backend['model'] = cfg.model
    backend['reasoning_effort'] = cfg.effort
    snapshot['ui']['fullscreen_exit_shortcuts'] = ['ALT+F4']
    snapshot['ui']['fullscreen_enter_shortcuts'] = []
    return snapshot
