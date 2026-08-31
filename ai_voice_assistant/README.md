# AI 語音管家 - 愛管家

這個專案目前是一個以 Windows 為主的桌面語音助手。主要流程如下：

`sounddevice` 錄音 → `silero-vad` 判斷語音起訖 → `sherpa-onnx` 偵測喚醒詞 → `faster-whisper` 轉文字 → LLM 串流回覆 → `edge-tts` 合成語音 → `sounddevice` 播放。

## 目前實作重點

- GUI 採用 `customtkinter`，啟動後會自動進入全螢幕，並以 Tk 回報的邏輯桌面尺寸套用 geometry，避免 Windows 顯示縮放下被重複縮小。
- public config / UI 目前開放五種 LLM 後端：`antigravity_cli`、`grok_cli`、`opencode_cli`、`codex_cli`、`claude_code`。
- 設定採 layered config：`config.default.json` 是 public 預設值，`config.local.json` 是每台機器自己的 private 設定；也可用 `AI_GOVERNESS_CONFIG` 指向替代的本機設定檔。
- v2.5 pipeline 是唯一 runtime，所有 voice、text、heartbeat 與 schedule turn 共用 typed identity、搶佔、取消與 metrics；不需要額外的總開關。
- `pipeline_v2_5` 只保留可獨立調校的效能選項，例如 streaming TTS、adaptive chunking、parallel speaker 與 bounded queue 大小。
- 預設 LLM 後端為 `antigravity_cli`；使用 Antigravity CLI 的 `agy` print mode，並在 Windows 透過 PTY 讀取回覆。
- `antigravity_cli` 使用 `ai_voice_assistant/agent_workspace/` 作為預設工作目錄。
- `opencode_cli` 使用 `opencode acp` 長連線，支援 ACP streaming、cancel、session resume/load、tool call keepalive，並以 runtime `OPENCODE_CONFIG_CONTENT` 預載 `MEMORY.md`。
- `grok_cli` 使用 `grok agent stdio` ACP v1 長連線，透過 temporary agent profile 預載 private `AGENTS.md` / `MEMORY.md`，並只把 tool turn 的 final message 送往 UI / TTS。
- `codex_cli` 仍完整支援，透過 Codex CLI app-server 建立長連線 thread，預設使用 `danger-full-access` + `approval_policy=never`，並會過濾 commentary，只保留最終回答給 UI 與 TTS。
- 支援語音模式與文字模式切換。
- 文字模式會直接送 LLM，不經過 Whisper，也不會觸發 TTS。
- 新增 `heartbeat` 定期巡檢：待機時會固定向 LLM 做背景巡檢，並依回覆決定靜默結束、僅 UI 顯示，或發出語音提醒。
- 新增 `presence_detection` 在場偵測：VAD 語音活動與鍵盤滑鼠活動都可更新「附近是否可能有人」狀態。
- Heartbeat 在文字模式下仍會運作，但提醒會降級成只顯示在 UI，不會強制朗讀。
- Heartbeat 的語音提醒會遵守最短播報間隔與最長字數限制，避免過度打擾。
- Heartbeat 永遠讓步給使用者互動；喚醒詞、手動收音、文字輸入、停止/打斷都會優先搶佔。
- Heartbeat 不會直接刷新 `last_interaction_time`；若連續 3 次巡檢結果都是 `[HEARTBEAT_NOP]`，才會主動 refresh LLM session，避免長時間待機後 session 過舊。
- 回覆播放結束後會進入熱監聽；是否啟用與秒數都可在設定抽屜調整。
- 待機時若啟用使用者活動提示，偵測到鍵盤輸入或滑鼠大幅移動後，會先播報提示語，再切進熱監聽。
- 若 `whisper_audio_archive.enabled = true`，每次送進 Whisper 的音訊都可額外保存成 `.wav`；若 `write_transcript_sidecar = true`，還會同步寫出同名 `.txt`。
- 支援在 `voice_profiles/<EnglishName>/` 內放入多個 `.wav` 建立家人聲音 profile，並在送 LLM 前附帶「可能是誰在說話」的提示；樣本過短時會自動略過。
- 左側狀態動畫的 runtime layered assets 位於 `assets/states/layers/`，使用共用背景與各狀態 PNG frames；若圖片缺失，UI 會退回既有動畫檔或文字狀態顯示。
- 日誌同時輸出到終端與 `logs/ai_voice_assistant-YYYY-MM-DD.log`；完整 LLM input/output 另以 plaintext 寫入 `logs/llm_io-YYYY-MM-DD.log`，預設保留 5 天。
- Heartbeat / presence / LLM 相關關鍵分支都有結構化 log event，方便追查是被略過、被搶佔、超時、靜默還是降級成 UI 顯示。

## 安裝、啟動與使用

> 完整步驟請參閱 [根目錄 README](../README.md)。

快速摘要：

```powershell
# 以下都從 repository root 執行
# 1. 建立 venv
python -m venv ai_voice_assistant\venv
.\ai_voice_assistant\venv\Scripts\python.exe -m pip install -r ai_voice_assistant\requirements.txt
# 若有 NVIDIA GPU：改安裝 ai_voice_assistant\requirements-cuda.txt

# 2. 下載 wake-word model
powershell -ExecutionPolicy Bypass -File .\scripts\download_models.ps1

# 3. 建立本機設定
copy ai_voice_assistant\config.example.json ai_voice_assistant\config.local.json

# 4. 啟動
.\start.bat

# 5. 測試
cd ai_voice_assistant
.\venv\Scripts\python.exe -m pytest -q
```

## 使用方式

- 語音模式下，說出喚醒詞後開始講話。
- 也可以直接按左下主按鈕跳過喚醒詞，立刻進入收音。
- 回覆播放中如果想打斷，可以再說一次喚醒詞，或按下「停止 / 打斷」。
- 切到文字模式後，右側輸入框可直接送出文字訊息。
- 若啟用 heartbeat，系統會在待機時定期巡檢；有提醒但附近無人時，內容會留在 UI，不一定朗讀。
- 若有啟用 Whisper 封存，音檔會出現在 `whisper_audio_archive/`；若 sidecar 功能開啟，同名 `.txt` 會一起記錄 transcript 與 speaker name。
- 家人聲音樣本請放在 `voice_profiles/<EnglishName>/`；系統會把資料夾名稱當成說話者名稱，並可自動重載新增或替換的 `.wav`。
- 全螢幕退出快捷鍵由 `ui.fullscreen_exit_shortcuts` 設定；預設為 `Esc`、`F11`。
- 進入全螢幕快捷鍵由 `ui.fullscreen_enter_shortcuts` 設定；預設為 `F11`，且只在 windowed 狀態生效。
  可使用 `CTRL`、`ALT`、`SHIFT` 組合鍵，以及英數鍵、`F1`–`F24`、`ESC`、`ENTER`、`SPACE`、`TAB`。

## 重要設定

- `config.default.json`：public 預設設定，應提交到 Git。
- `config.example.json`：給新使用者複製成 `config.local.json` 的範例。
- `config.local.json`：本機 private 設定，會被 `.gitignore` 排除；UI 儲存設定時也會寫入這裡。
- `heartbeat.enabled`：是否啟用待機巡檢。
- `heartbeat.interval_minutes`：巡檢週期，程式內最短會保護到 10 秒，Heartbeat prompt 也會使用這個實際間隔描述自己。
- `presence_detection.enabled`：是否啟用在場偵測；關閉後 heartbeat 仍會運作，但提醒會傾向降級成 UI 顯示。
- `presence_detection.ttl_seconds`：最近一次活動後，持續判定「附近有人」的秒數。
- `presence_detection.audio_triggers_presence`：VAD 偵測到語音時是否更新在場狀態。
- `presence_detection.input_triggers_presence`：鍵盤或滑鼠活動是否更新在場狀態。
- `pipeline_v2_5.streaming_tts`：是否在 Edge TTS 收到足夠 MP3 資料後漸進解碼。
- `pipeline_v2_5.adaptive_chunking`：是否使用首句優先的自適應 TTS 切句。
- `pipeline_v2_5.parallel_speaker`：是否讓說話者辨識與 STT 並行；同時間最多一個 speaker task。
- `pipeline_v2_5.playback_queue_chunks` / `tts_queue_chunks`：播放與 TTS 的 bounded queue 大小。

## 目前架構

- `core/assistant.py`：整合狀態機、背景 asyncio loop、感知執行緒、語音/文字模式與打斷流程。
- `core/pipeline/`：v2.5 的 turn arbitration、typed identity、取消範圍、backend registry 與 latency metrics。
- `core/heartbeat.py`：提供 thread-safe 的 heartbeat scheduler，負責固定時間觸發巡檢。
- `core/presence_tracker.py`：追蹤最近的語音/輸入活動，提供「附近是否可能有人」判定。
- `core/audio_capture.py`：使用固定大小佇列收錄音訊，滿了會丟棄最舊 chunk。
- `core/audio_player.py`：播放 PCM 佇列，並追蹤硬體緩衝中的尾端播放狀態，避免過早判定播放結束。
- `core/whisper_audio_archive.py`：把每次 Whisper 輸入另存成 `.wav` 與 sidecar `.txt`。
- `core/speaker_recognizer.py`：載入 `voice_profiles/` 內的資料夾並做說話者辨識提示，優先使用 `resemblyzer`，不可用時退回 MFCC。
- `core/sentence_builder.py`：保留 500ms pre-roll，避免首字被截斷。
- `llm/codex_cli_client.py`：Codex CLI 後端，使用 Codex app-server thread / turn 介面，並過濾 commentary 只保留 final answer。
- `llm/antigravity_cli_client.py`：Antigravity CLI 後端，使用 `agy` print mode，並清理 CLI terminal output 後交給 UI 與 TTS。
- `llm/opencode_cli_client.py`：OpenCode CLI 後端，使用 ACP v1 session，model/mode 透過 `session/set_config_option` 設定，`permission_mode: "yolo"` 對 subprocess 注入 `permission: "allow"`。
- `llm/grok_cli_client.py`：Grok Build ACP 後端，負責 explicit authentication、well-known executable fallback、temporary private context profile、allow-once permission 與 final-segment buffering。
- `tts/edge_tts_engine.py`：使用 PyAV 解碼 Edge TTS 的 MP3；可依 `pipeline_v2_5.streaming_tts` 選擇漸進解碼或整句解碼。
- `ui/main_window.py`：左側角色舞台、右側對話面板、右上設定抽屜，以及輸入區與狀態摘要。

## 開源與私人資料邊界

這個專案設計成「source code 可共享、runtime state 不進 Git」；這不代表所有處理都離線：

- 可以提交：`core/`、`llm/`、`tts/`、`ui/`、`utils/`、`tools/`、`tests/`、`agent_workspace_template/`、`config.default.json`、`config.example.json`。
- 不要提交：`config.local.json`、`logs/`、`whisper_audio_archive/`、`voice_profiles/`、`agent_workspace/*.md`、`models/` 內下載的模型、`venv/`。
- 第一次啟動時，程式會建立 private folders，並從 `agent_workspace_template/` 複製缺少的初始記憶檔到 `agent_workspace/`。
- 若要在 GitHub 分享 bugfix，請只分享 source code patch，不分享 private memory、語音、logs 或模型檔。
- Groq STT 會傳送音訊；Edge TTS 會傳送合成文字；cloud-backed LLM CLI 會傳送 prompt/context；啟用 web search 時會傳送查詢。請依需要改用 local Whisper、BlueMagpie 並停用網路工具。

## 測試與記錄

- 日常驗證請在已啟用 `venv` 的 `ai_voice_assistant` 目錄執行 `pytest -q`，或直接使用 `venv\Scripts\python.exe -m pytest -q`。
- `run_test.py` 目前會針對 `core`、`llm`、`tts`、`utils` 產出 coverage 報表；建議同樣使用專案 `venv` 執行。
- 完整測試數量會隨版本增加；請以當次 `pytest -q` 的結束狀態與輸出為準。

## 已知限制

- `tts.volume` 雖然引擎與 config 都支援，但目前 UI 尚未提供對應控制。
- 喚醒詞偵測器目前會使用 `wake_word.keywords_file` 與 `wake_word.model_dir`；若設定為相對路徑，會自動以 `ai_voice_assistant/` 為基準解析。
- `wake_word.keyword`、`pinyin`、`boosting_score` 這類純文字設定目前仍未直接接到偵測器。
- 說話者辨識只會提供「可能是誰」的提示，不應視為身分保證。
- Heartbeat 目前只在 `IDLE_LISTEN` 待機狀態巡檢；進入收音、思考、回覆、熱監聽後都會讓步給使用者互動。
