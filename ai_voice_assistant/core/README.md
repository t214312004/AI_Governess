# 核心音訊與邏輯層（Core）

`core` 目錄放的是語音助手的主要協調邏輯。

## `assistant.py`

目前的總控模組，負責：

- 建立 `AudioCapture`、`AudioPlayer`、`VoiceActivityDetector`、`Transcriber`、`WakeWordDetector`、`SentenceBuilder`
- 建立 `SpeakerRecognizer` 與 `WhisperAudioArchive`
- 啟動背景 asyncio event loop
- 啟動感知執行緒 `_perception_loop()`
- 管理五段狀態：`IDLE_LISTEN`、`COLLECTING`、`SENDING`、`SPEAKING`、`HOT_LISTEN`
- 處理語音模式 / 文字模式切換
- 處理打斷、熱監聽、session refresh、以及使用者活動提示語

## `audio_capture.py`

- 使用 `sounddevice.InputStream`
- 錄音資料寫入 `queue.Queue(maxsize=200)`
- 佇列滿時會先丟棄最舊資料，再放入最新 chunk，避免 callback 被阻塞

## `audio_player.py`

- 使用 `sounddevice.OutputStream`
- 從播放佇列取出 PCM 資料並補進硬體緩衝
- 支援殘留 PCM 續播（`_residual_data`）
- `is_playing` 會同時考慮播放佇列、殘留資料與硬體緩衝中的尾端音訊，避免過早回報播放完成
- 打斷時會清空佇列並在 callback 中丟出 `sd.CallbackStop()`

## `vad.py`

- 使用 `silero-vad`
- 為了避開 Windows 中文路徑問題，會先把模型檔讀進記憶體再 `torch.jit.load`
- 每次偵測到 `end` 事件後會重置內部狀態，避免長時間漂移

## `sentence_builder.py`

- 根據 VAD 的 `start` / `end` 事件收集音訊
- 內建 500ms pre-roll 緩衝，補回開頭語音
- `reset()` 只清空目前句子狀態，保留 pre-roll buffer

## `wake_word.py`

- 使用 `sherpa-onnx` 的 keyword spotter
- 實際讀取 `wake_word.keywords_file` 與 `wake_word.model_dir`
- 若設定為相對路徑，會先解析成相對於 `ai_voice_assistant/` 的實際路徑
- 一旦命中喚醒詞，會重建 sherpa stream，避免同一命中結果重複回報

## `transcriber.py`

- 封裝 `faster-whisper`
- 會從 `config.json` 讀入 `model_size`、`device`、`compute_type`、`language`、`initial_prompt`
- Windows 下會額外把 venv 內 NVIDIA DLL 路徑加入 `PATH`

## `speaker_recognizer.py`

- 從 `voice_profiles/` 載入家人聲音樣本
- 優先使用 `resemblyzer`；若環境中不可用，會自動退回 `torchaudio` 的 MFCC 特徵
- 僅做提示用途，回傳的是「可能是誰」而不是絕對身分判定
- 會根據最短音長與相似度門檻決定是否輸出結果，並在 profile 檔案異動時自動重載

## `whisper_audio_archive.py`

- 可選擇把每次送進 Whisper 的音訊另存成 `.wav`
- 可同步產生 sidecar `.txt`，記錄 utterance_id、wav_path、transcript 與 speaker name

## `state_machine.py`

- 使用 `threading.Lock()` 保護狀態轉換
- `check_hot_listen_timeout()` 會自動把逾時的 `HOT_LISTEN` 拉回 `IDLE_LISTEN`
- `interrupt()` 會把目前狀態強制切到 `COLLECTING`
