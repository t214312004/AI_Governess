"""Persist device name + host API, resolving fresh indexes when opening streams."""
import sounddevice as sd


def list_audio_devices(kind):
    apis = sd.query_hostapis()
    return [(f'{item["name"]} · {apis[item["hostapi"]]["name"]}',
             {'name': item['name'], 'hostapi': apis[item['hostapi']]['name']})
            for item in sd.query_devices() if item['max_input_channels' if kind == 'input' else 'max_output_channels'] > 0]


def resolve_audio_device(selection, kind):
    if selection is None:
        return None
    apis = sd.query_hostapis()
    for index, item in enumerate(sd.query_devices()):
        if (item['max_input_channels' if kind == 'input' else 'max_output_channels'] > 0 and
                item['name'] == selection['name'] and apis[item['hostapi']]['name'] == selection['hostapi']):
            return index
    raise ValueError(('麥克風' if kind == 'input' else '播放裝置') + '已離線，請在「聲音與裝置」重新選擇。')


def check_audio_devices(settings):
    audio = settings['audio']
    if settings.get('interaction', {}).get('voice_input', True):
        sd.check_input_settings(device=resolve_audio_device(audio.get('input_device'), 'input'),
            channels=1, dtype='int16', samplerate=audio['input_sample_rate'])
    if settings.get('interaction', {}).get('voice_output', True):
        sd.check_output_settings(device=resolve_audio_device(audio.get('output_device'), 'output'),
            channels=1, dtype='int16', samplerate=audio['output_sample_rate'])
