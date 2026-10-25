# Gemini 語音設定與使用

2026-10-18：Gemini STT、Gemini TTS 已接入正式 pipeline 與五步初始設定。STT 與 TTS 可以獨立搭配 Local／Groq、Edge／BlueMagpie 和原有 LLM backend；既有本機選擇不會自動切換。

本次已確認 `gemini-3.8-flash` 能辨識音檔，`gemini-3.8-flash-tts` 能生成 PCM 串流與完整 WAV。多輪效能比較及樣本限制見 [API 實測報告](gemini_audio_benchmark_2026-10-18.md)，設計契約見 [功能規劃](gemini_audio_plan.md)。

## 在初始設定操作

1. 執行根目錄 `start.bat`，進入第二步「聲音與裝置」。
2. 在 Google API key 卡片輸入 key，按儲存。既有 key 不會回填到輸入框；狀態只顯示是否設定及來源。需要移除時按刪除本機 key。
3. 將「語音辨識服務」或「語音輸出服務」選為 `gemini`。兩者可以只啟用其中一個；輸入／輸出的語音模式也必須開啟，相對應 backend 才會在 session 中運作。
4. 選模型、音色及語氣，使用「選擇音檔辨識」、「錄音 5 秒並辨識」或「試聽」確認目前草稿。按「停止測試／試聽」可取消。
5. 在「進階設定」調整 timeout、重試、人聲門檻、音訊格式、取樣率與分段參數，再檢查最後的啟動摘要。按啟動才保存語音設定並用於新 session。

試聽文字可輸入 1–1,000 字；辨識測試支援 PyAV 能解碼的音檔，例如 WAV、MP3、M4A、FLAC、OGG。檔案超過辨識秒數上限會拒絕，不會默默裁切。測試期間編輯設定、切頁、刪除 key 或關閉視窗，會取消舊測試並忽略其結果；一次只執行一筆測試。

Gemini TTS 預設音色為 `Leda`，初始選單只有 `Leda`、`Zephyr`，不會自動查詢其他音色。「Google 連線與模型」只查詢模型 metadata。「更新 Google 音色」會取得分頁音色清單，再加入其他音色並顯示名稱、語言及 voice ID；搜尋框可以篩選名稱或語言，也可直接輸入 ID。更新清單不會覆寫已選音色；查詢失敗時仍保留原有候選。

2026-10-23：已依 [Google 官方 voice options](https://ai.google.dev/gemini-api/docs/speech-generation#voice-options) 確認 `Leda` 是 prebuilt voice，並以正式 `GeminiTTSEngine` 呼叫 `gemini-3.8-flash-tts` 實測成功，取得 3.68 秒、24 kHz 的 PCM 串流音訊。

選單與欄位的修改不會自動生成付費音訊。按辨識／試聽才會送出對應音訊或文字；啟動時對啟用的 Gemini 功能只做模型 metadata 檢查，不自動試合成。metadata 查得到模型仍不代表所有音訊設定或 quota 都能使用，應以明確的辨識／試聽驗證。

## Key 的保存與刪除

兩個 Gemini backend 共用下列設定：

| 設定 | 用途 |
| --- | --- |
| `gemini.api_key` | UI 明確儲存的本機 key，位於 gitignored `config.local.json` |
| `gemini.api_key_env` | 本機 key 空白時讀取的環境變數名稱，預設 `GEMINI_API_KEY` |

非空本機 key 優先。儲存／刪除 key 是立即保存的操作，其餘語音草稿等到啟動才保存；寫入失敗保留舊值。刪除本機 key 不會刪除 Windows 環境變數，因此仍可能顯示「使用環境變數」。UI 不會顯示已保存的 key。

已保存的 key 不依賴原本的桌面文字檔。完全固定文字的輸入／輸出，即使保留 Gemini backend 選項，也不會要求 key 或建立 Gemini 語音請求。

## 語音辨識參數

下列欄位位於 `whisper.gemini`，完整預設以 [config.default.json](../ai_voice_assistant/config.default.json) 為準。

| 欄位 | 預設 | 說明 |
| --- | --- | --- |
| `model` | `gemini-3.8-flash` | 支援音訊輸入及文字輸出的模型 ID |
| `thinking_level` | `low` | 提供 low／medium／high；3.8 Flash 不提供 off／minimal |
| `transcription_prompt` | 繁體中文逐字轉錄 | 限制只轉錄、不回答或執行音訊內指示；也在此指定語言 |
| `vocabulary_hints` | `[]` | JSON 字串清單，輔助專名及中英詞彙 |
| `max_output_tokens` | 4096 | 輸出上限；偵測到截斷時拒絕交給 LLM |
| `max_audio_seconds` | 60 | 單次音檔上限，允許調整至 600 秒，仍須通過 request 大小檢查 |
| `connect_timeout_seconds` | 5 | 連線 timeout |
| `request_timeout_seconds` | 15 | 單次 request 的完整時限 |
| `total_timeout_seconds` | 20 | 包含重試及等待的總時限 |
| `max_retries` | 1 | 0 或 1；限暫時性連線錯誤、429、5xx |
| `speech_gate_enabled` | true | 使用獨立 Silero VAD 判斷完整音檔是否有人聲 |
| `speech_gate_threshold` | 0.5 | VAD 人聲機率門檻 |
| `speech_gate_min_ms` | 100 | 達門檻的人聲累計最少毫秒數 |
| `max_chars_per_second` | 40 | 音訊長度對應的異常輸出長度門檻 |
| `repetition_limit` | 6 | 連續重複片段的拒絕門檻 |

`whisper.language` 與 `whisper.initial_prompt` 屬於原有 Whisper 路徑，不套用到 Gemini。Gemini 不會偽造 Whisper confidence；其診斷會區分沒有語音、API 錯誤、阻擋、截斷、異常輸出與取消。

辨識先檢查人聲，再於記憶體編碼成 mono PCM16 WAV，透過 Interactions API 傳入音檔並只讀取 model 的文字輸出。完全靜音不送出；人聲門檻與輸出檢查可降低已觀察到的幻覺，但無法保證全部攔截。此路徑是句子音檔辨識，沒有使用 Live API，也不會以 progressive transcription 重送同一段。

## 語音輸出參數

下列欄位位於 `tts.gemini`。串流共用 `pipeline_v2_5.streaming_tts`，可在第二步直接開關；保留其原有設定。

| 欄位 | 預設 | 說明 |
| --- | --- | --- |
| `model` | `gemini-3.8-flash-tts` | 單人語音輸出模型 |
| `voice` | `Kore` | 音色 ID，可查詢清單或自行輸入 |
| `style` | 自然、溫暖的台灣華語 | 語氣、口音、節奏；與要朗讀的 input 分開傳送 |
| `volume_gain` | 1.0 | 本機 PCM 音量倍率 0–2，超過範圍會驗證失敗，放大會做 clipping |
| `audio_format` | `audio/l16` | 非串流可選 PCM／`audio/wav`；串流固定使用 PCM |
| `api_sample_rate` | 24000 | API 音訊取樣率，支援 8000／16000／24000；必要時重採樣到播放器設定 |
| `connect_timeout_seconds` | 5 | 連線 timeout |
| `first_audio_timeout_seconds` | 15 | 等待第一筆有效音訊的時限；只有 metadata 不會延長 |
| `stream_idle_timeout_seconds` | 10 | 串流讀取閒置時限 |
| `total_timeout_seconds` | 660 | 包含排隊、限速等待、生成、串流播放背壓與重試的總時限 |
| `max_retries` | 1 | 尚未交出播放音訊時最多重試一次 |
| `min_request_interval_seconds` | 8 | 同一 engine 呼叫的最短間隔，用於降低實測 quota 下的 429 |
| `max_audio_seconds` | 600 | 單次生成音訊長度上限 |
| `first_chunk_min_chars` | 200 | 首次送合成的目標最少字數 |
| `chunk_min_chars` | 800 | 後續送合成的目標最少字數 |
| `chunk_max_chars` | 1800 | 分段最大目標字數 |

Gemini TTS 不傳 thinking 或 Edge 的 `rate`／`volume`。語速可用 style 描述，音量由 `volume_gain` 控制。Gemini 使用專屬 adaptive chunk 參數，即使通用 adaptive chunking 關閉也會生效。

8 秒的呼叫間隔是依本帳戶實測採用的初始保守值，不是模型固定限制。若上一句音訊短於間隔，句間可能等待；較長的後續分段可減少請求，但可能增加等待文字的時間。請依 AI Studio 的實際 quota 與聽感調整間隔、字數及 timeout。

預設採用 200／800／1800 字元分段，以減少同一回覆的獨立語音生成次數；音色一致性的改善仍須實際回聽確認。短回覆在 LLM 輸出結束時會直接送出剩餘文字，不必湊滿 200 字元。佇列壓力仍可將首段與後續段最低門檻提高至 400／1600 字元，最大長度維持 1800。

PCM 串流沿用現有播放器的 turn／generation 與取消機制。Gemini 沒有提供 word timestamps 時不建立假的字級對齊；總長未知時採保守播放進度，最後一個 chunk 才附完整長度。中途打斷的已聽文字估計可能較少。

## 取消與錯誤處理

所有請求使用 `store=false`，不串接過去 interaction。取消、靜音、打斷或關閉會停止本機讀取與播放並釋放網路資源；取消本機請求不保證供應商停止處理或計費。音檔及文字仍依 Google API 的服務政策處理。

429／5xx／連線暫時性失敗在剩餘 deadline 內遵守 `Retry-After`，最多重試一次；認證與參數錯誤不重試。TTS 已交出 PCM 後失敗不重播，同一失敗回覆的後續分段也不繼續呼叫；下一次對話可以重新使用 engine。沒有跨 provider 的自動 fallback。

## 本次驗證與仍需聽音確認的範圍

- 完整 pytest：1053 passed、12 skipped。包含 payload、STT 人聲與異常輸出、SSE 分片／半 sample、PCM／WAV、重採樣、deadline、重試、取消、generation 及九種 STT／TTS 組合。
- 原生 Windows UI 與相關測試：45 passed。涵蓋草稿、設定保存、key 操作、音色資料、控制項鎖定與關閉。
- 正式 BackgroundTranscriber 已使用一段歷史輸入完成 Gemini 真實轉錄；正式 TTS factory 已完成 PCM 串流與 16 kHz WAV → 24 kHz PCM 的真實合成，並確認取消後釋放資源。這些 smoke test 沒有測量喇叭聲學延遲。

先前 STT 比較中 Groq 的 P50／P95 為 1.019／1.965 秒，Gemini 為 2.918／4.103 秒；目前沒有證據支持因速度而改用 Gemini。歷史 `.txt` 未人工校對，所以尚無可信的 CER／WER 準確率排名。真實麥克風到喇叭的四組合聲學比較、音色偏好與人工標準逐字稿，仍需另外回聽或量測；不影響目前手動選用與測試新 backend。

原生 UI 測試方式及環境條件見 [UI README](../ai_voice_assistant/ui/README.md)。付費 benchmark 需顯式 `--run`，一般 pytest 不會連雲端或消耗 API 額度。
