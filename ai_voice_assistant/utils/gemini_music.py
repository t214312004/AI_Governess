"""One bounded CLI generation. Never retry an uncertain paid request."""
import json
import os
from pathlib import Path
import time

from core.music_catalog import catalog
from llm.model_catalog import CliCatalog
from utils.gemini_api_cli import resolve_executable, MUSIC_MODEL
from utils.gemini_audio import resolve_api_key


class MusicGenerationError(ValueError):
    def __init__(self,reason,*,uncertain=False):
        self.reason,self.uncertain=reason,uncertain
        super().__init__(reason)


def generate(settings,request,folder,cancel):
    try:
        if settings.get('music',{}).get('model',MUSIC_MODEL)!=MUSIC_MODEL:
            raise ValueError('model')
        executable=resolve_executable(settings.get('gemini_api_cli',{}).get('executable',''))
        credential=settings.get('gemini',{})
        key=resolve_api_key(credential.get('api_key',''),credential.get('api_key_env','GEMINI_API_KEY'))
        version=CliCatalog._run([executable,'--version'],cancel,time.monotonic()+10).strip()[:100]
    except Exception:
        raise MusicGenerationError('cli_or_key_not_ready') from None
    folder=Path(folder).resolve()
    folder.mkdir(parents=True,exist_ok=True)
    labels={s['id']:s['en'] for s in catalog()['styles']}
    instruction=(f"Create original music. Styles: {', '.join(labels[g] for g in request['genre_ids']) or 'creative original'}. "
                 f"Approximately {request['requested_duration_seconds']} seconds, with a complete natural ending. "
                 "Do not imitate a specific artist or existing song.\n")
    instruction+=('Strictly instrumental: no vocals, humming, chanting or spoken words.\n' if request['instrumental'] else
                  'Include singing. Language: '+(request['language'] or 'Traditional Chinese / Taiwanese Mandarin')+'. '+request['vocal_description']+'\n')
    instruction+=request['style_notes']+'\n'+request['prompt']
    if request['lyrics']:
        instruction+='\nSing these original lyrics in order:\n'+request['lyrics']
    prompt=folder/'prompt.txt'
    prompt.write_text(instruction,encoding='utf-8')
    body=folder/'body.json'
    body.write_text('{"store":false}',encoding='utf-8')
    destination=folder/'generated.mp3'
    env=dict(os.environ,GEMINI_API_KEY=key)
    for name in ('GOOGLE_API_KEY','GEMINI_ACCESS_TOKEN','GEMINI_DEBUG','DEBUG'):
        env.pop(name,None)
    timeout=float(settings.get('music',{}).get('generation_timeout_seconds',180))
    command=[executable,'--no-interactive','music','--model',MUSIC_MODEL,'-f',str(prompt),
             '--body','@'+str(body),'--out',str(destination),'--output-format','json','--timeout',f'{timeout:g}s']
    try:
        raw=CliCatalog._run(command,cancel,time.monotonic()+timeout+10,env=env)
        result=json.loads(raw)
        path=Path(result.get('path','')).resolve()
        if path.parent!=folder or not path.is_file() or path.suffix.lower() not in ('.mp3','.wav'):
            raise ValueError('missing_artifact')
        if result.get('status','completed')!='completed':
            raise ValueError('incomplete')
        return path,{'response_id':str(result.get('response_id',''))[:500], 'provider_version':version}
    except Exception:
        raise MusicGenerationError('remote_result_unknown',uncertain=True) from None
