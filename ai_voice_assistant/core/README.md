# 核心音訊與邏輯層（Core）

`core` 目錄放的是語音助手的主要協調邏輯。

## `assistant.py`

目前的總控模組，負責：

- 建立音訊與管線元件；固定文字輸入略過 VAD、Whisper、wake word、speaker recognizer 與麥克風啟動，固定文字輸出略過播放器啟動與 TTS warmup
- 透過 `core/pipeline/` 統一協調 voice、text、heartbeat 與 schedule turn
- 啟動背景 asyncio event loop
- 啟動感知執行緒 `_perception_loop()`
- 管理五段狀態：`IDLE_LISTEN`、`COLLECTING`、`SENDING`、`SPEAKING`、`HOT_LISTEN`
- 依啟動設定獨立控制語音輸入／輸出與執行中靜音；文字輸入也可走串流語音回覆流程
- 處理打斷、熱監聽、session refresh、以及使用者活動提示語
- 為一般對話附加時間、session UI／輸出模式及 active whiteboard metadata；active state 不表示 renderer 此刻可見或成功附著

## 巡檢、排程與白板

- `heartbeat.py`：背景 scheduler；public default 關閉。`assistant.py` 限制巡檢在 08:00–21:00 與 `IDLE_LISTEN`，prompt 只准讀既有 context，不執行 shell 或寫檔工具；NOP／SILENT 控制標記不顯示給家人。
- `presence_tracker.py`：依近期 VAD／鍵盤滑鼠活動估計在場狀態，不能保證身份或現場有人。
- `schedule_poller.py`：獨立於 heartbeat 的固定輪詢，預設每秒檢查；只在待機執行到期任務，使用者互動優先。
- `schedule_manager.py` / `schedule_models.py`：唯一的 schedule、draft、run、pending report state writer；支援 once／daily／weekly、miss policy、確認與 undo。報告正文注入及 delivered 標記由 app 管理，工具只列 availability。
- `whiteboard_manager.py`：單一 active Markdown／image／HTML、資產驗證、替換、hide／restore、HTML reload、close 與內容讀取；status 提供持久化顯示狀態與 HTML 剩餘額度及不可用原因。
- `html_usage.py`：HTML 每日額度、process-safe lock、原子寫入與 Taipei 換日；只計可見 HTML，排除鎖定及睡眠，損壞時停用 HTML。
- `session_settings.py`：五步設定的型別／範圍驗證、完整 config snapshot 與固定本次 backend、model、effort、輸入／輸出、額度、字級的 `SessionConfig`。

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

- `Transcriber` 與 `BackgroundTranscriber` 支援 local `faster-whisper` 與 Groq transcription API；local 模型在背景載入，準備完成後才進入 session
- layered config 讀入 `backend`、local 模型設定、語言／initial prompt，以及 Groq API key／環境變數、model、timeout 與 confidence gate
- Windows 下會額外把 venv 內 NVIDIA DLL 路徑加入 `PATH`

## `speaker_recognizer.py`

- 從 `voice_profiles/` 載入家人聲音樣本
- 優先使用 `resemblyzer`；若環境中不可用，會自動退回 NumPy / SciPy 的 MFCC 特徵
- 無法讀取的個別 WAV 只會被略過，不會導致整個 backend 降級
- 僅做提示用途，回傳的是「可能是誰」而不是絕對身分判定
- 會根據最短音長與相似度門檻決定是否輸出結果，並在 profile 檔案異動時自動重載

## `whisper_audio_archive.py`

- 可選擇把每次送進 Whisper 的音訊另存成 `.wav`
- 可同步產生 sidecar `.txt`，記錄 utterance_id、wav_path、transcript 與 speaker name

## `state_machine.py`

- 使用 `threading.Lock()` 保護狀態轉換
- `check_hot_listen_timeout()` 會自動把逾時的 `HOT_LISTEN` 拉回 `IDLE_LISTEN`
- `interrupt()` 會把目前狀態強制切到 `COLLECTING`
