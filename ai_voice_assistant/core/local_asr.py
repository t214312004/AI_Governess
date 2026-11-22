"""Resolve local model profiles once for production and preview."""
from __future__ import annotations

import ctypes
import os

from utils.breeze_model import DEFAULT_MODEL_DIR, model_path, readiness

BREEZE_DEFAULTS = {'model_dir': DEFAULT_MODEL_DIR, 'device': 'cuda',
                   'compute_type': 'int8_float16', 'language': 'auto', 'beam_size': 5}


def local_profile_kwargs(config):
    return {'local_profile': config.get('whisper', 'local_profile', default='standard') or 'standard',
            'breeze_settings': config.get('whisper', 'breeze_asr25', default={}) or {}}


def available_memory_bytes():
    if os.name != 'nt':
        return None
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                    *[(key, ctypes.c_ulonglong) for key in ('total', 'available', 'page_total',
                      'page_available', 'virtual_total', 'virtual_available', 'extended')]]
    state = MemoryStatus()
    state.length = ctypes.sizeof(state)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
        return state.available
    return None


def resolve_local_profile(profile, standard, breeze_settings=None):
    if profile == 'standard':
        return dict(standard)
    if profile != 'breeze_asr25':
        raise ValueError(f'不支援的本地辨識設定：{profile}')
    settings = dict(BREEZE_DEFAULTS, **(breeze_settings or {}))
    if settings['language'] not in ('auto', 'en', 'zh'):
        raise ValueError('Breeze 解碼語言須為 auto、en 或 zh。')
    if type(settings['beam_size']) is not int or not 1 <= settings['beam_size'] <= 5:
        raise ValueError('Breeze beam_size 須為 1–5。')
    if settings['device'] not in ('cpu', 'cuda', 'auto'):
        raise ValueError('Breeze 運算裝置須為 cpu、cuda 或 auto。')
    if settings['compute_type'] not in ('int8', 'int8_float32', 'int8_float16', 'float16', 'float32', 'bfloat16'):
        raise ValueError('Breeze 運算精度不受支援。')
    if settings['device'] == 'cpu' and settings['compute_type'] not in ('int8', 'int8_float32', 'float32'):
        raise ValueError('Breeze 使用 CPU 時，請選 int8、int8_float32 或 float32。')
    reason = readiness(settings['model_dir'])
    if reason:
        raise ValueError(reason)
    available = available_memory_bytes()
    if available is not None and available < 2 * 1024**3:
        raise ValueError('可用 RAM 不足 2 GiB，暫不載入 Breeze；請關閉其他程式後重試。')
    return {'model_size': str(model_path(settings['model_dir'])), 'device': settings['device'],
            'compute_type': settings['compute_type'], 'language': settings['language'],
            'initial_prompt': '', 'local_files_only': True,
            'decoding_options': {'beam_size': settings['beam_size']}}
