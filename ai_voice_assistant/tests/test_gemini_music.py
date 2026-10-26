"""Provider boundary: exact model, private key environment, bounded cancellation."""
import json
from pathlib import Path
import threading
from unittest.mock import patch

import pytest

from utils.gemini_music import generate, MusicGenerationError


def request():
    return {'genre_ids':['folk'],'requested_duration_seconds':45,'instrumental':True,
            'style_notes':'木吉他','prompt':'花園裡的小探險','lyrics':'','language':'','vocal_description':''}


def test_provider_uses_only_lyria35_and_never_passes_key_in_argv(tmp_path):
    settings={'gemini':{'api_key':'PRIVATE_KEY'},'music':{'model':'lyria-3.5','generation_timeout_seconds':30}}
    calls=[]
    def run(argv,cancel,deadline,**kwargs):
        calls.append((argv,kwargs))
        assert cancel.wait(.001) is False
        if '--version' in argv:return 'gemini-api version 0.4.4'
        destination=Path(argv[argv.index('--out')+1]);destination.write_bytes(b'test audio')
        assert json.loads((destination.parent/'body.json').read_text())=={'store':False}
        assert kwargs['env']['GEMINI_API_KEY']=='PRIVATE_KEY'
        assert 'PRIVATE_KEY' not in ' '.join(argv)
        assert '--model' in argv and argv[argv.index('--model')+1]=='lyria-3.5'
        assert 'no vocals' in (destination.parent/'prompt.txt').read_text(encoding='utf-8')
        return json.dumps({'status':'completed','path':str(destination),'response_id':'public-response'})
    with patch('utils.gemini_music.resolve_executable',return_value='gemini-api.exe'),patch('utils.gemini_music.CliCatalog._run',side_effect=run):
        path,metadata=generate(settings,request(),tmp_path,threading.Event())
    assert path.is_file() and metadata['provider_version']=='gemini-api version 0.4.4'
    assert len(calls)==2


def test_invalid_model_fails_before_starting_cli(tmp_path):
    with patch('utils.gemini_music.CliCatalog._run') as run:
        with pytest.raises(MusicGenerationError) as error:generate({'music':{'model':'lyria-3'}},request(),tmp_path,threading.Event())
        assert error.value.uncertain is False
        run.assert_not_called()


def test_remote_failure_and_outside_artifact_are_never_retried(tmp_path):
    settings={'gemini':{'api_key':'PRIVATE_KEY'}}
    for returned in (ValueError('provider diagnostic containing PRIVATE_KEY'),json.dumps({'path':str(tmp_path.parent/'outside.mp3')})):
        with patch('utils.gemini_music.resolve_executable',return_value='gemini-api.exe'),patch('utils.gemini_music.CliCatalog._run',side_effect=['v0.4.4',returned]) as run:
            with pytest.raises(MusicGenerationError) as error:generate(settings,request(),tmp_path,threading.Event())
            assert error.value.uncertain is True and 'PRIVATE_KEY' not in str(error.value)
            assert run.call_count==2  # version plus exactly one generation attempt
