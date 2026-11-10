"""Presentation metadata for browsing startup settings by everyday tasks."""

# Keep storage keys independent of the wording shown in the UI. Unknown local
# groups remain accessible in the final topic rather than disappearing.
TOPICS = {
    '__listening__': ('收音與辨識', '調整收音靈敏度、說話停頓、辨識服務與喚醒詞。',
                      ('vad', 'whisper', 'wake_word', 'audio')),
    '__speaking__': ('朗讀與播放', '調整合成聲音、朗讀斷句與語音處理效能。',
                     ('tts', 'semantic_chunker', 'pipeline_v2_5')),
    '__assistant__': ('AI 與工具', '調整回應等待時間、工具權限與服務連線。',
                      ('llm', 'gemini', 'gemini_api_cli')),
    '__family__': ('互動與家人', '調整接續聆聽、主動關懷、聲紋與在場判斷。',
                   ('hot_listen', 'user_activity_prompt', 'heartbeat', 'speaker_recognition', 'presence_detection')),
    '__display__': ('畫面與音樂', '調整角色動畫、白板內容與音樂創作限制。',
                    ('ui', 'whiteboard', 'music')),
    '__storage__': ('保存與排程', '調整錄音保存位置、排程服務與其他本機設定。',
                    ('whisper_audio_archive', 'schedule', 'interaction')),
}

GROUP_HELP = {
    'audio': '設定收音與播放的取樣率、緩衝大小；裝置選擇請到「聲音與裝置」。',
    'whisper': '依所選辨識服務調整連線、辨識品質與人聲檢查。',
    'wake_word': '指定喚醒模型與詞檔；編輯與錄音測試請到「互動與使用限制」。',
    'tts': '依所選語音服務調整合成品質、等待時間與音訊格式。',
    'semantic_chunker': '指定在哪些標點分段，讓朗讀更符合說話節奏。',
    'pipeline_v2_5': '調整語音處理、合成佇列與分段；不確定時可保留預設值。',
    'hot_listen': '回覆後繼續等待說話，省去再次使用喚醒詞。',
    'user_activity_prompt': '設定操作鍵盤或滑鼠時，主動詢問的觸發條件。',
    'heartbeat': '設定是否定期主動關懷，以及兩次關懷之間的時間。',
    'speaker_recognition': '調整辨識家人聲音的門檻，以及聲紋樣本的位置。',
    'presence_detection': '設定哪些活動代表有人在場，以及狀態保留多久。',
    'ui': '調整角色動畫；對話字級請到「互動與使用限制」。',
    'whiteboard': '設定可顯示的內容、大小限制與朗讀時的音效音量。',
    'music': '設定創作次數、預估費用與本機曲庫容量。',
    'whisper_audio_archive': '設定是否保存錄音、逐字稿，以及保存資料夾。',
    'schedule': '調整排程檢查頻率、通知數量與排程資料位置。',
    'gemini': '設定 Google 服務使用的金鑰環境變數名稱。',
    'gemini_api_cli': '指定 Gemini API CLI；安裝與模型查詢請到「AI 服務」。',
}


def topic_for(group):
    return next((key for key, (_, _, groups) in TOPICS.items() if group in groups), '__storage__')


def topic_groups(topic, settings):
    groups = list(TOPICS[topic][2])
    if topic == '__storage__':
        known = {group for _, _, items in TOPICS.values() for group in items}
        groups.extend(group for group in settings if group not in known)
    return [group for group in groups if group in settings]


def section_info(path, labels):
    """Return a stable section key, human title and short purpose statement."""
    group, key = path[0], path[-1]
    if group == 'vad':
        if key in ('threshold', 'speech_pad_ms', 'fallback_silence_rms_threshold'):
            return (group, 'sensitivity'), '收音靈敏度', '容易把雜音當人聲，或經常漏收開頭時，可從這裡調整。'
        if key in ('no_speech_timeout_seconds', 'command_timeout_seconds'):
            return (group, 'duration'), '收音時間限制', '設定沒有說話時等多久，以及一次最多收音多久。'
        return (group, 'pause'), '停頓與語尾', '說話還沒結束就被截斷時，可檢查停頓與語尾等待時間。'
    if group == 'audio':
        direction = 'input' if key.startswith('input_') else 'output'
        return (group, direction), '麥克風收音格式' if direction == 'input' else '喇叭播放格式', GROUP_HELP[group]
    if group == 'llm' and len(path) == 2:
        if key in ('failure_window_seconds', 'failure_threshold', 'circuit_cooldown_seconds'):
            return (group, 'failure'), '連續失敗時暫停', '設定錯誤累積到幾次時暫停，以及多久後再嘗試。'
        return (group, 'waiting'), 'AI 回應等待時間', '調整第一段回覆、完整回覆與串流停滯的等待上限。'
    if group in ('llm', 'whisper', 'tts') and len(path) > 2:
        provider = {'groq': 'Groq', 'gemini': 'Google Gemini', 'bluemagpie': 'BlueMagpie'}.get(path[1], labels.get(path[1], path[1]))
        title = provider + (' · 語音辨識' if group == 'whisper' else ' · 語音合成' if group == 'tts' else ' · 工作目錄與工具')
        return (group, path[1]), title, GROUP_HELP.get(group, '設定此 AI 服務的工作目錄、工具與連線方式。')
    return (group,), labels.get(group, group), GROUP_HELP.get(group, '調整此功能的細節；不確定時可保留預設值。')


def field_title(path, labels):
    title = labels.get('.'.join(path), labels.get(path[-1], path[-1]))
    if len(path) > 3:
        title = ' / '.join([*(labels.get(part, part) for part in path[2:-1]), title])
    return title


def matches_search(path, query, labels):
    # Search descriptions and identifiers, never saved values or credentials.
    _, title, description = section_info(path, labels)
    # Cross-references after a semicolon point to another page, not these fields.
    description = description.split('；', 1)[0]
    terms = ' '.join((*path, '.'.join(path), *(labels.get(part, part) for part in path),
                      field_title(path, labels), title, description)).casefold()
    return all(word in terms for word in query.casefold().split())
