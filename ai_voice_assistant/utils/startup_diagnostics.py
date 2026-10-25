"""Local readiness checks and credential-safe diagnostics for startup."""
import os
from pathlib import Path
import re

APP_DIR = Path(__file__).resolve().parents[1]


def app_path(value):
    path = Path(value)
    return path if path.is_absolute() else APP_DIR / path


def safe_error(exc, settings):
    text = str(exc) or type(exc).__name__
    secrets = []
    def visit(value):
        if not isinstance(value,dict): return
        for key,item in value.items():
            if key=='api_key' and isinstance(item,str) and item: secrets.append(item)
            if key.endswith('_env') and isinstance(item,str) and os.environ.get(item): secrets.append(os.environ[item])
            visit(item)
    visit(settings)
    for secret in sorted(secrets,key=len,reverse=True): text=text.replace(secret,'[已遮罩]')
    text=re.sub(r'(?i)(authorization[=:]\s*)(?:bearer\s+)?[^\s,;]+',r'\1[已遮罩]',text)
    text=re.sub(r'(?i)(bearer\s+|(?:api[_-]?key|x-goog-api-key)[=:]\s*)[^\s,;]+',r'\1[已遮罩]',text)
    return ' '.join(text.split())[:450]


def bluemagpie_readiness(settings):
    values=settings['tts']['bluemagpie']
    missing=[]
    for key,title in (('worker_python','worker Python'),('worker_script','worker 腳本')):
        if not values.get(key) or not app_path(values[key]).is_file(): missing.append(title)
    for key,title in (('speaker_centroid_path','聲音特徵檔'),('prompt_wav_path','參考音檔')):
        if values.get(key) and not app_path(values[key]).is_file(): missing.append(title)
    if bool(values.get('prompt_text')) != bool(values.get('prompt_wav_path')):
        missing.append('參考音檔與逐字稿必須成對提供')
    return missing


def local_readiness(settings):
    rows=[]
    voice=settings.get('interaction',{})
    if voice.get('voice_input',True):
        wake=settings['wake_word']
        model=app_path(wake['model_dir'])
        names=('encoder-epoch-12-avg-2-chunk-16-left-64.onnx','decoder-epoch-12-avg-2-chunk-16-left-64.onnx',
               'joiner-epoch-12-avg-2-chunk-16-left-64.onnx','tokens.txt')
        ready=all((model/name).is_file() for name in names) and app_path(wake['keywords_file']).is_file()
        rows.append(('喚醒詞', '檔案已備妥；尚未錄音測試' if ready else '缺少模型／詞檔；仍可手動收音'))
        folder=app_path(settings['speaker_recognition']['profile_dir'])
        count=sum(1 for child in folder.glob('*') if child.is_dir() and any(child.glob('*.wav'))) if folder.is_dir() else 0
        rows.append(('家人聲紋', f'{count} 位已有 WAV 樣本；尚未驗證辨識' if settings['speaker_recognition']['enabled'] else '本次停用'))
    if voice.get('voice_output',True) and settings['tts']['backend']=='bluemagpie':
        missing=bluemagpie_readiness(settings)
        rows.append(('BlueMagpie', '尚缺：'+'、'.join(missing) if missing else 'worker 路徑已確認；尚需試聽驗證'))
    return rows


def validate_local_selection(settings):
    voice=settings.get('interaction',{})
    if voice.get('voice_input',True) and settings['whisper']['backend']=='groq':
        values=settings['whisper']['groq']
        if not (values.get('api_key') or os.environ.get(values.get('api_key_env','GROQ_API_KEY'))):
            raise ValueError('請在「聲音與裝置」填入 Groq API key，或設定對應環境變數。')
    if voice.get('voice_output',True) and settings['tts']['backend']=='bluemagpie':
        missing=bluemagpie_readiness(settings)
        if missing: raise ValueError('BlueMagpie 尚缺：'+'、'.join(missing)+'。請回「聲音與裝置」完成設定。')
