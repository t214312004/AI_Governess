"""Stable startup field metadata; never infer nullable types from saved values."""
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from pathlib import Path


@lru_cache(maxsize=1)
def public_defaults():
    return json.loads(Path(__file__).resolve().parents[1].joinpath('config.default.json').read_text(encoding='utf-8'))


def default_value(path, fallback=None):
    value = public_defaults()
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return fallback
        value = value[key]
    return value


ENUMS = {
    ('music', 'model'): ('lyria-3.5',),
    ('audio', 'input_sample_rate'): (8000, 16000),
    ('whisper', 'backend'): ('local', 'groq', 'gemini'),
    ('whisper', 'device'): ('cpu', 'cuda', 'auto'),
    ('whisper', 'compute_type'): ('int8', 'int8_float32', 'int8_float16', 'int8_bfloat16', 'int16', 'float16', 'float32', 'bfloat16', 'auto', 'default'),
    ('tts', 'backend'): ('edge', 'bluemagpie', 'gemini'),
    ('tts', 'bluemagpie', 'device'): ('cpu', 'cuda'),
    ('tts', 'bluemagpie', 'mode'): ('worker',),
    ('whisper', 'gemini', 'thinking_level'): ('low', 'medium', 'high'),
    ('tts', 'gemini', 'audio_format'): ('audio/l16', 'audio/wav'),
    ('tts', 'gemini', 'api_sample_rate'): (8000, 16000, 24000),
    ('llm', 'codex_cli', 'sandbox'): ('read-only', 'workspace-write', 'danger-full-access'),
    ('llm', 'codex_cli', 'approval_policy'): ('never', 'on-request', 'on-failure', 'untrusted'),
    ('llm', 'antigravity_cli', 'auth_method'): ('oauth-personal',),
    ('llm', 'antigravity_cli', 'subscription_only'): (True,),
    ('llm', 'antigravity_cli', 'mode'): ('yolo', 'default', 'auto_edit'),
    ('llm', 'antigravity_cli', 'auto_approve_scope'): ('once', 'session'),
    ('llm', 'antigravity_cli', 'stream_mode'): ('final_segment', 'incremental'),
    ('whiteboard', 'markdown_renderer'): ('ctk_markdown',),
}
MODEL_SIZES = ('tiny', 'tiny.en', 'base', 'base.en', 'small', 'small.en', 'medium', 'medium.en', 'large-v1', 'large-v2', 'large-v3', 'large', 'distil-large-v2', 'distil-large-v3', 'distil-medium.en', 'distil-small.en', 'large-v3-turbo', 'turbo')
HELP = {
    ('music', 'daily_generation_limit'): '每天最多提交的音樂創作次數；未確認結果也計入，避免重複費用。',
    ('music', 'daily_budget_usd'): '每天音樂創作預估費用上限（USD）；以每首 $0.08 保守估算，實際依 Google 帳單。',
    ('music', 'max_storage_mb'): '本機曲庫容量上限（MiB）；滿額時保留既有歌曲並停止新增。',
    ('music', 'max_audio_seconds'): '匯入與生成音檔可接受的最長秒數；不保證模型精準遵守期望長度。',
    ('music', 'model'): '所有音樂風格、純音樂與歌曲統一使用 lyria-3.5，不自動切換模型。',
    ('gemini_api_cli', 'executable'): '留白自動尋找已驗證的 Gemini API CLI 安裝，也可指定 gemini-api.exe；更新不改系統 PATH。',
    ('audio', 'input_sample_rate'): 'Silero VAD 支援 8000／16000 Hz；一般建議 16000 Hz。',
    ('audio', 'input_block_size'): '每個收音區塊：16000 Hz 用 512；8000 Hz 用 256。',
    ('whisper', 'model_size'): '較大模型需要更多記憶體；可選常用模型，或輸入 Hugging Face repo／本機模型路徑。',
    ('whisper', 'device'): 'cpu 適用一般電腦；cuda 需要 NVIDIA GPU 與相容環境。',
    ('whisper', 'compute_type'): 'CPU 通常選 int8；CUDA 可選 float16 或 int8_float16。',
    ('whisper', 'language'): '例如 zh、en；填 auto 自動判斷語言。',
    ('tts', 'bluemagpie', 'seed'): '空白表示隨機；指定整數可重現生成結果。',
    ('tts', 'rate'): '百分比，-30% 至 +30%；0% 為原速度。',
    ('tts', 'volume'): '相對原音量 -100% 至 +100%；+0% 為原音量。',
    ('whiteboard', 'html_daily_minutes'): '0 表示停用 HTML；0–1440 分鐘，Asia/Taipei 每日 00:00 重置。',
    ('ui', 'chat_font_size'): '16–32 px；僅調整主畫面對話字級。',
    ('llm', 'antigravity_cli', 'auth_method'): '固定使用 Google AI Pro personal OAuth；不使用 API key／Google Cloud。',
    ('llm', 'antigravity_cli', 'subscription_only'): '必須保持啟用；session 驗證 Google AI Pro 後才可推論。',
    ('llm', 'antigravity_cli', 'executable'): '留白使用已驗證的官方 ACP 安裝；指定路徑需有同版 localharness_external.exe。',
    ('llm', 'antigravity_cli', 'mcp_servers'): '可選的 ACP MCP server 設定；不會自動匯入舊 CLI 設定。',
    ('llm', 'antigravity_cli', 'filesystem_roots'): '額外授權的檔案資料夾；~ 為目前使用者家目錄。workspace 與程式目錄固定包含；可加其他既有資料夾，不接受整個磁碟根目錄。',
    ('llm', 'antigravity_cli', 'mode'): 'yolo 自動批准一般工具；家庭敏感操作仍由愛管家的工具規則控制。',
}
PATH_KEYS = {'project_dir', 'model_dir', 'profile_dir', 'directory', 'state_dir', 'temp_dir', 'tool_payload_dir', 'worker_python', 'worker_script', 'keywords_file', 'speaker_centroid_path', 'prompt_wav_path', 'executable', 'tool_path'}
MULTILINE_KEYS = {'initial_prompt', 'transcription_prompt', 'style', 'prompt_text', 'text'}


@dataclass(frozen=True)
class FieldSpec:
    default: object
    options: tuple = ()
    kind: str = 'text'
    help: str = ''


def field_spec(path, fallback=None):
    path = tuple(path)
    value = default_value(path, fallback)
    key = path[-1]
    # Durations accept fractional seconds, including migrated CLI timeouts.
    # Keep counters/sample sizes integer even when their saved value is wrong.
    if key.endswith('_seconds') and type(value) is int:
        value = float(value)
    kind = ('json_list' if path == ('llm', 'antigravity_cli', 'mcp_servers') else
            'nullable_int' if path == ('tts', 'bluemagpie', 'seed') else
            'bool' if type(value) is bool else 'list' if isinstance(value, list) else
            'directory' if key in PATH_KEYS and (key.endswith('_dir') or key in ('directory', 'project_dir')) else
            'file' if key in PATH_KEYS else 'multiline' if key in MULTILINE_KEYS else
            'secret' if key == 'api_key' else 'number' if type(value) in (int, float) else 'text')
    options = ENUMS.get(path, MODEL_SIZES if path == ('whisper', 'model_size') else ())
    help_text = HELP.get(path, '')
    if not help_text and type(value) in (int, float):
        if key.endswith('_seconds'): help_text = '單位：秒。'
        elif key.endswith('_minutes'): help_text = '單位：分鐘。'
        elif key.endswith('_ms'): help_text = '單位：毫秒。'
        elif key.endswith('_bytes'): help_text = '單位：bytes。'
        elif key.endswith('_chars'): help_text = '單位：字元數。'
    if kind in ('file', 'directory') and not help_text:
        help_text = '相對路徑以 ai_voice_assistant 資料夾為基準；也可選擇完整路徑。'
    return FieldSpec(value, tuple(options), kind, help_text)


class SettingsError(ValueError):
    def __init__(self, path, message):
        self.path = tuple(path)
        self.message = message
        super().__init__(f'{".".join(path)}：{message}')


def validate_field(path, value):
    path = tuple(path)
    key = path[-1]
    def fail(message):
        raise SettingsError(path, message)
    if path==('music','directory'):
        from core.music_manager import library_root
        try:
            library_root(Path(__file__).resolve().parents[1],value)
        except (ValueError,TypeError):
            fail('請選專用曲庫資料夾，不可留白或使用程式／專案／磁碟根目錄')
    if path == ('tts', 'bluemagpie', 'seed'):
        if value is not None and type(value) is not int: fail('請填整數或留白表示隨機')
    elif path in (('audio', 'input_device'), ('audio', 'output_device')):
        if value is not None and (not isinstance(value, dict) or set(value) != {'name', 'hostapi'} or
                not all(isinstance(v, str) and v.strip() for v in value.values())):
            fail('請重新選擇音訊裝置')
    elif path in ENUMS and value not in ENUMS[path]:
        fail('請選擇：' + '／'.join(str(v) for v in ENUMS[path]))
    elif path == ('llm', 'antigravity_cli', 'filesystem_roots'):
        if not isinstance(value, list) or any(not isinstance(p, str) or not p.strip() for p in value):
            fail('請填資料夾路徑清單；每個項目須為非空字串')
    elif path == ('whisper', 'model_size'):
        if not isinstance(value, str) or not value.strip() or (value not in MODEL_SIZES and '/' not in value and '\\' not in value):
            fail('請選常用模型，或填入 repo ID／模型路徑')
    elif path == ('whisper', 'language'):
        if not isinstance(value, str) or not re.fullmatch(r'[a-z]{2,3}|auto', value): fail('請填 zh、en 等語言代碼，或 auto')
    elif path in (('tts', 'rate'), ('tts', 'volume')):
        if not isinstance(value, str) or not re.fullmatch(r'[+-]\d+%', value): fail('格式例如 +0%、-10%')
        bound = 30 if key == 'rate' else 100
        if not -bound <= int(value[:-1]) <= bound: fail(f'請填 -{bound}% 至 +{bound}%')
    if type(value) in (int, float):
        if path[0]=='music':
            bounds={'generation_timeout_seconds':(10,600),'daily_generation_limit':(0,1000),
                    'daily_budget_usd':(0,1000),'max_storage_mb':(1,1048576),'max_audio_seconds':(10,300)}
            if key in bounds and not bounds[key][0]<=value<=bounds[key][1]:
                fail(f'必須介於 {bounds[key][0]}–{bounds[key][1]}')
        signed = key in ('animation_foreground_y_offset_px', 'avg_logprob_threshold', 'seed')
        if not signed and value < 0: fail('不得小於 0')
        positive = ('timeout_seconds' in key or key in ('input_sample_rate', 'output_sample_rate', 'input_block_size',
            'output_block_size', 'animation_interval_ms', 'tts_queue_chunks', 'playback_queue_chunks', 'poll_interval_ms',
            'poll_interval_seconds', 'interval_minutes', 'min_duration_seconds'))
        if positive and value <= 0: fail('必須大於 0')
        if key in ('threshold', 'html_audio_duck_volume', 'fallback_silence_rms_threshold', 'no_speech_prob_threshold',
                   'min_transcript_similarity', 'min_nonzero_ratio', 'min_score_margin') and not 0 <= value <= 1:
            fail('必須介於 0–1')
        if path == ('ui', 'chat_font_size') and not 16 <= value <= 32: fail('必須介於 16–32 px')
        if path == ('whiteboard', 'html_daily_minutes') and not 0 <= value <= 1440: fail('必須介於 0–1440 分鐘')
