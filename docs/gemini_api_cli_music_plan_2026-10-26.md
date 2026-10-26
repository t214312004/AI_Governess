# Gemini API CLI、TTS 與白板音樂庫實測規劃書

**後續調整已完成**：本機每種風格均有單一風格入門歌曲；已加入刪歌／回收區／復原並修正音量滑桿。最新結果見[追加調整紀錄](music_updates_2026-10-26.md)。

日期：2026-10-26，Asia/Taipei。涵蓋官方資料核對、現有 API Key 實測、導入設計及正式實作。TTS 保留原有直接呼叫與串流路徑。

**正式實作已完成（同日）**：初始 UI 的 CLI 更新／模型查詢、固定 `lyria-3.5`、背景創作、永久曲庫、精緻白板播放器、12 種中英大風格、多風格篩選、agent 操作工具，以及免 HTML 時間均已接入。新增真實生成與播放確認；[完整實作與驗收紀錄](music_implementation_2026-10-26.md)、[操作指南](music.md)。以下原研究與設計保留當時脈絡，現行狀態以本段與末尾實作章節為準。

**追加需求（同日，已實作）**：agent 的能力告知、工具呼叫引導及播放器控制均已交付；**官方音樂播放器不計入 HTML 每日時間，也不受 HTML 額度為 0、用完或紀錄故障影響**。一般 HTML 遊戲照常限制。

**風格選單追加需求（同日）**：以小孩認識音樂為主，首版採約 12 種容易理解的中英對照大風格，不細分大量流派。所有選項預先提供，即使曲庫尚無該類歌曲也可瀏覽、選擇並作為創作引導；歌曲可同時屬於多種風格，篩選採多選（7C）。

## 1. 決策摘要

- **TTS 建議保留現行 Python 直接呼叫 Interactions API 的串流實作。** `gemini-api tts` 是完整音檔生成工具；本次量測沒有支持為了降低對話延遲而改走這個子命令。
- **音樂生成已實際成功，初輪三首已由使用者試聽並接受。** 使用者明確偏好 `lyria-3.5`；後續生成任何風格都固定使用此模型，禁止自動降級或 fallback 到 Clip。另補測 Lyria 3.5 的兩種純音樂。
- **音樂播放器已正式整合。** 「非同步生成 → 永久保存 → 白板曲庫與風格篩選 → 播放」已落地，使用專屬 Edge renderer 與既有 audio ducking；實作與驗收見第 11 章。
- **agent 引導和控制是必要功能。** 所有對話 backend 都須收到 app 注入的能力與操作契約，能創作、查詢工作、找歌、開播放器與控制播放；工具結果須區分排隊、生成完成與實際播放器回報。
- **官方音樂播放器不限 HTML 時間。** 使用專用的 `music` 白板內容與 app 內建播放器，HTML 遊戲仍沿用原有時間限制。
- **風格選單採兒童導向的雙語大分類。** 預先內建 12 種風格與一句特色說明，空曲庫仍完整呈現；以多對多關係保存歌曲風格，預設符合任一所選風格即可找到歌曲。
- **「只支援 API Key」需要修正。** 實測版本 `v0.4.4` 同時接受 API Key 與外部提供的 OAuth access token，但沒有把 Google AI Pro 登入轉成訂閱額度的流程。API Key／Bearer 是認證方式，計費權益是另一件事。[固定版本認證原始碼](https://github.com/google-gemini/gemini-api-cli/blob/v0.4.4/internal/cli/auth.go)

## 2. 官方 CLI、認證與費用

### 工具身份與安裝紀錄

這次使用 `google-gemini/gemini-api-cli` 的 **`gemini-api 0.4.4`**，release 於 2026-10-23 發布，Windows x86_64 portable binary，沒有改系統 PATH、安裝全域套件或覆寫認證。下載 archive 的 SHA-256 已與 GitHub release asset digest 核對：

```text
2ec5b226a99f665a714d77602b2e0992aec58af74a44c5329de9dd5b384bad2e
```

官方將此 CLI 定位成供 agent／script 呼叫 Gemini 能力的獨立工具，每次執行由呼叫者提供上下文；`tts` 預設 `gemini-3.8-flash-tts`，`music` 預設 `lyria-3.5`。這與專案 LLM backend 的 `gemini`／Antigravity 登入方式不可互換。[官方 README](https://github.com/google-gemini/gemini-api-cli/blob/v0.4.4/README.md)、[release](https://github.com/google-gemini/gemini-api-cli/releases/tag/v0.4.4)

### Google AI Pro 可以抵用什麼

| 層次 | 本次確認 | 實際含義 |
|---|---|---|
| API Key | 本機既有 `gemini.api_key` 已成功完成 TTS 與 music | 沿用此 key，不需新增 Google 登入 |
| OAuth access token | CLI global flag `--access-token` 和 `auth login` 可接受外部 token；僅核對介面與 source，未實際用 token 呼叫 | 不是內建瀏覽器登入／refresh-token 授權流程；不能因此推論能用 Pro 額度 |
| Google AI Pro 產品使用額度 | 未找到此 CLI 能兌接該額度的官方流程 | 不應將 Antigravity／Gemini app 的訂閱用量視為這個 API 的可用額度 |
| 訂閱附帶的 eligible Google Cloud credits | 官方說明 Pro／Ultra 的 developer benefit 可包含 Cloud credits，且 eligible credits 可用於 Gemini API | 需先領取、套用到正確 billing account／project；依 credit 的適用範圍決定能否抵扣 |
| 此帳戶實際抵扣狀況 | 未讀取 Billing 帳務與 credit redemption 狀態 | 成功呼叫只能證明模型權限可用，不能證明本次免費或已抵扣 |

Google 官方 FAQ 說明：Prepay 帳戶可能需要先有有效的預付餘額，eligible Cloud credits 才會優先抵扣；預付餘額歸零後可能停止使用這些 credits。Google Cloud welcome／free-trial credit 與 eligible developer credits 也不能混為一談。[Developer Program FAQ](https://developers.google.com/profile/help/faq)、[Gemini API Billing](https://ai.google.dev/gemini-api/docs/billing#how-do-google-cloud-credits-work-with-prepay)

因此準確的回答是：**這個 CLI 可使用 API Key，也接受外部 OAuth token；不能直接假設它消耗 Google AI Pro 的產品使用額度，但符合條件且已兌換的 Cloud credits 有可能抵 API 帳單。** 本次沒有替使用者啟用計費、預付、兌換或更改方案。

### 價格快照

2026-10-26 官方 Standard paid tier：`lyria-3-clip-preview` 每次 USD 0.04，`lyria-3.5` 每首 USD 0.08。初輪三首合計 USD 0.16，補測兩首 Lyria 3.5 再 USD 0.16，五首音樂定價合計 **USD 0.32**；未來統一每首 USD 0.08 的模型。Gemini 3.8 Flash TTS 當期 input USD 0.50／1M text tokens、output USD 9／1M audio tokens，25 audio tokens／秒；官網列出 2027-01-01 後價格調整。所有數字是定價推算，並非 Billing 實付紀錄。[官方價格](https://ai.google.dev/gemini-api/docs/pricing)

依本次回傳 usage，24 次 TTS 為 1,464 input tokens、10,310 audio output tokens，Standard 估計 USD 0.093522；五次盲聽分析的 Gemini 3.8 Flash 估計 USD 0.011938。加上音樂約 **USD 0.42546（約 USD 0.43）**，未計稅務、匯率及實際 credit 抵扣。

## 3. 現有程式調查

### TTS 實際路徑

```text
core/assistant.py 的文字分段
  → tts/factory.py
  → tts/gemini_tts_engine.py: GeminiTTSEngine
  → utils/gemini_audio.py: tts_payload
  → POST https://generativelanguage.googleapis.com/v1beta/interactions
  → SSE audio/l16 → 24 kHz mono PCM → core/audio_player.py
```

本機目前 `tts.backend=gemini`、`pipeline_v2_5.streaming_tts=true`、voice `Leda`；使用溫暖、開朗的台灣華語 style。public default 的串流開關為 false，不能將 default 誤當成本機實際值。已有 timeout、限流、取消、PCM 格式檢查及播放進度追蹤。

`tts.gemini` 預設首段至少 200 字、後續至少 800 字、最多 1800 字，請求間隔 8 秒；這些會影響端到端對話等待。本次從「完整文字已交給 TTS」開始量測，不包含等 LLM 累積文字的時間。

### 白板現況及限制

- `core/whiteboard_manager.py` 的 `show_html` 只接受 `agent_workspace/apps/` 內的 HTML；保存 active content、hide／restore 與每日用量。
- `ui/session_window.py` 使用 `ui/embedded_html.py: NativeHtmlRenderer`，沿用 `ui/html_whiteboard.py` 的本機 HTTP handler 與音訊橋接。
- HTML `<audio>` 和本機相對路徑素材已可用；CSP 封鎖外部 API。金鑰與 music 生成流程必須留在 Python，不能放進 JavaScript。
- `MainWindow._sync_whiteboard_audio_ducking` 在 `SPEAKING` 時降低 HTML 音量；現有手動靜音優先。此能力可沿用。
- 目前 static handler 一次讀完檔案，沒有專門處理 `HEAD`／`Range`。短 MP3 可以播放，長曲庫可靠 seek、續播和低記憶體傳送需要補強。
- hide／reload／替換白板會卸載 HTML renderer；播放隨頁面停止。localStorage 可以保存 track／position／volume，恢復後仍應由使用者按播放。
- HTML 白板目前預設每日 30 分鐘，現有程式以 `content_type == 'html'` 進行開啟檢查、計時與到期關閉。依追加需求，正式音樂播放器須新增專用內容路徑與獨立生命週期；不能直接呼叫原 `show_html`，否則仍會被計時／阻擋。

## 4. TTS 比較設計

工具：[scripts/gemini_api_capability_probe.py](../scripts/gemini_api_capability_probe.py)。同一台 Windows、同一 key、同一模型 `gemini-3.8-flash-tts`、同一 voice `Leda`，兩種原創繁體中文文字各跑三輪，每輪輪替順序，請求開始時間至少相隔 8 秒。

| Arm | 實際做法 | 用途 |
|---|---|---|
| `engine_current` | 呼叫真正 `GeminiTTSEngine.synthesize_stream`；保留本機 style 與串流開關 | 現行產品 TTS 路徑的參考 |
| `engine_unstyled` | 同一引擎、同一串流方式；style 清空 | 檢查 style 是否可能混淆比較；仍保留 app 的 input schema |
| `rest_cli_payload` | 讀 CLI `--dry-run -o json` 的 body，以 `httpx` 直接送出 | 與 CLI 完全相同 JSON body 的對照；unary |
| `cli_tts` | 真正啟動 `gemini-api.exe tts -f ... --voice Leda --out ... -o json` | 包含 process 啟動、網路、解碼與寫檔的整體時間 |

共 24 個 TTS 操作；不做付費失敗自動補跑。app arm 將 `max_retries` 設為 0，排除重試時間；每次建立獨立 engine，排除前一個請求的 8 秒排隊時間。原生 CLI SDK 的預設錯誤處理則保留。

測量 `first_nonzero_ms`（軟體端第一個非零 PCM 可供播放）與 `elapsed_ms`（完整生成接收完成），並保存每次音訊秒數、格式、SHA-256、usage（有提供時）及失敗紀錄。CLI 不提供早期 PCM，計時取完整檔案可用時間。未啟動音效卡，不代表實際喇叭聲學起音；錄音前導靜音與播放器緩衝也可能影響真人聽感。

### 結果

24／24 成功，沒有排除慢樣本。每個 cell 各三次，中位數如下；短句 32 字、長段文字 136 字（含標點）。

| 文字 | Arm | 首個非零 PCM／檔案可播放 | 整段生成完成 | 音訊長度中位數 |
|---|---|---|---|---|
| 短句 | 現有 engine，保留 style | **1.224 秒** | **2.689 秒** | 6.40 秒 |
| 短句 | engine，移除 style | 1.260 秒 | 2.764 秒 | 6.08 秒 |
| 短句 | REST，與 CLI 相同 body | 4.083 秒 | 4.083 秒 | 6.36 秒 |
| 短句 | CLI `tts` | 4.465 秒 | 4.465 秒 | 7.08 秒 |
| 長段 | 現有 engine，保留 style | **1.503 秒** | **8.348 秒** | 26.48 秒 |
| 長段 | engine，移除 style | 1.374 秒 | 8.132 秒 | 28.80 秒 |
| 長段 | REST，與 CLI 相同 body | 9.264 秒 | 9.264 秒 | 26.24 秒 |
| 長段 | CLI `tts` | 10.621 秒 | 10.621 秒 | 28.56 秒 |

CLI 長段三次分別 **10.621、93.231、10.246 秒**，93 秒那次輸出 28.56 秒 WAV 且 exit code 0，stderr 空白。它保留在原始資料與 min/max 中；沒有可觀測證據能區分是 server 等待、網路波動或 CLI 內部處理，不將它斷言成 CLI 本身 bug。

在這組樣本，CLI 短句起音比現有引擎晚約 3.24 秒、長段晚約 9.12 秒；就算忽略慢樣本，仍沒有明顯加速。24 個音檔總長 412.4 秒，皆可解碼。音訊長度不同也說明 model 語速會波動，故同時提供生成時間與音訊時長，不把它解讀成精確同波形效能測試。

### 如何解讀

`gemini-api tts` 的實際 dry-run body 是 `stream:false`、`store:false`、`response_format:{type:"audio"}`，HTTP endpoint 與 app 相同。官方 source 也是等 `Agent.Run` 完成才抽出音訊並寫檔，沒有一條專供 CLI 使用的加速 TTS 通道。[v0.4.4 tts source](https://github.com/google-gemini/gemini-api-cli/blob/v0.4.4/internal/cli/custom/tts.go)

CLI 沒有專門的 `tts --style` 或 `tts --stream` flag。通用的 `agent run` 仍能傳完整 body／串流事件，但要再做事件解析、PCM 邊界、取消和 process 管理；本次沒有將該通用路徑視為已實測的即時音訊 backend。官方 API 原本就支援 stream PCM。[官方 TTS streaming](https://ai.google.dev/gemini-api/docs/speech-generation#streaming-speech-generation)

三輪、兩種文字只能判斷這台機器／key／時段的可行性，不能作為所有模型負載下的速度承諾；沒有報不可靠的 P95 或統計顯著性。CLI／REST 是不同次生成，差值含模型與網路波動，不能直接稱為純 process overhead。對話更重視 first audio；整段生成較快也不等於比較早能開始說話。

## 5. 音樂生成實測與試聽

五個 prompt、完整原始結果、音檔與試聽頁保存在本機忽略目錄：`tool_payloads/gemini_api_eval_20261026/run1/`。試聽頁可直接用瀏覽器開 `listen.html`；本次亦啟動 `http://127.0.0.1:8765/listen.html`。server 關閉後可用文末指令重開。

| 原創曲目 | 模型／指定條件 | 實際音訊 | CLI 完成時間 |
|---|---|---|---|
| 雨夜書桌 | Clip；78 BPM、Rhodes／bass／soft drums，Lo-fi，無人聲 | 30.772 秒，744,659 bytes | 13.944 秒 |
| 午後的小步舞 | Clip；100 BPM、3/4、木吉他與 cello pizzicato，無鋼琴／synth／人聲 | 30.616 秒，740,898 bytes | 17.719 秒 |
| 把今天慢慢唱完 | Lyria 3.5；約 60 秒、108 BPM、中文女聲 synth-pop、指定八句歌詞與重複副歌 | 65.985 秒，1,589,773 bytes | 29.563 秒 |
| 雨夜書桌・Lyria 3.5（補測） | Lyria 3.5；中文指示、約 45 秒、78 BPM、無人聲／哼唱 Lo-fi | 62.720 秒，1,511,406 bytes | 22.220 秒 |
| 午後的小步舞・Lyria 3.5（補測） | Lyria 3.5；中文指示、約 45 秒、100 BPM、強調三拍子、木吉他與大提琴 | 51.304 秒，1,237,433 bytes | 20.597 秒 |

五首均以 PyAV 完整解碼成功，44,100 Hz、2 channels、非靜音；不是只有建立空檔或拿到成功文字。其中四首解碼後 floating-point peak 略超過 1.0，這可能是 lossy MP3 解碼 overshoot，不能據此宣稱聽到破音。試聽頁預設 60% 音量；正式播放器也應保留音量 headroom，避免無條件增益。

### 指定內容是否確實做到

API 成功、格式與長度已驗證；風格、樂器、拍號及逐字歌詞另做不提供目標 prompt 的模型聽音描述。該結果是機器輔助判讀，不能當真人音樂鑑賞或精確 BPM／拍號量測。

| 樣本 | 模型盲聽的描述 | 本次判定與限制 |
|---|---|---|
| Clip Lo-fi | 電鋼琴、bass、電子鼓；Lo-fi／Chillhop；無人聲；估計 80–85 BPM | 大方向與要求一致；78 BPM 沒有做訊號分析確認 |
| Clip 木吉他 | 指彈木吉他、無人聲；估計 75–80 BPM、4/4；沒有明確描述大提琴 | 木吉他與無人聲成立；指定三拍子／編制未驗證通過 |
| Lyria 3.5 中文歌 | 中文女聲、synth／bass／鼓、副歌重複；估計 80–85 BPM | 大方向與結構符合；108 BPM 未驗證；逐字歌詞存在疑點 |
| Lyria 3.5 Lo-fi 補測 | 電鋼琴、bass、Lo-fi 鼓、4/4；估計 75–80 BPM；描述為帶男聲無詞哼唱 | 曲風大方向符合，但「完全無人聲／哼唱」疑似未遵守，需真人核對；45 秒要求實際 62.72 秒 |
| Lyria 3.5 木吉他補測 | 尼龍弦吉他、無人聲；可能 3/4 或 6/8、偏三拍；估計 65–75 BPM | 較接近要求的三拍子聽感，但拍號、100 BPM 和大提琴編制仍未確證；長度 51.30 秒 |

中文歌的原詞第三句是「愛管家陪我輕輕唱」，盲聽轉錄成「白管家陪我清唱」。這可能是唱詞／發音偏差，也可能是 reviewer 誤聽，不能單憑 ASR 文字宣稱歌詞確定錯誤。其餘七句及副歌重複在該次轉錄中與要求一致。所有版本的機器描述均認為結尾自然，未提及明顯技術性破音，但這不取代真人音質判斷。

可支持的結論是 **Lyria 3.5 能產生不同大類型、可聽的音樂，使用者已接受初輪品質；精準秒數、完全排除人聲、BPM、樂器編制與逐字歌詞不能當成硬性保證**。補測沒有刻意反覆重生直到只剩符合 prompt 的版本，原始樣本與偏差全部保留。

**使用者回饋已收到：**「我聽完試聽頁面了，都 OK」，並明確表示比較喜歡 `lyria-3.5`，希望將來只用這個模型製作所有類型。這代表初輪聽感可接受，不代表逐字歌詞、BPM、拍號已逐項通過人工量測。補測版另列，沒有把尚未試聽的版本記成人工驗收通過。

官方說明 Lyria 3.5 長度可用 prompt 引導但非精確保證；目前不支援 multi-turn 音樂編輯，同 prompt 不保證同結果，且含 SynthID 音訊浮水印。本次所用曲詞均為原創。官方建議先用 Clip 試 prompt，但**本專案依使用者偏好，全程使用 `lyria-3.5`，包含預覽、短曲、純音樂及歌曲**。[官方 music guide](https://ai.google.dev/gemini-api/docs/music-generation)

## 6. 建議的正式架構

```text
Sophia / UI 送出音樂要求
  → tools/music_tool.py（小型命令介面；只接收受控 payload）
  → core/music_manager.py（建立 job、限制併發、永久保存）
  → CLI provider / gemini-api music（Python 注入 key；不經 shell 字串）
  → staging .part.mp3 → 解碼、雜湊、metadata 檢查 → atomic publish
  → music_library/catalog.sqlite3 + tracks/ + metadata/
  → music_tool show-player → WhiteboardManager.show_music（專用 music 內容）
  → app 內建 MusicPlayerRenderer → 受控曲庫／音訊路由 → Edge <audio> → 既有 ducking
  ↔ MusicPlaybackController（agent 播放指令、UI 指令、播放器實際狀態與 ack）
```

### 曲庫與檔案配置

```text
ai_voice_assistant/
  music_library/                      # 新 private runtime 資料夾，gitignored
    catalog.sqlite3                   # authoritative：tracks、jobs、schema_version
    tracks/<uuid>.mp3                 # 已完成音檔；永久保存
    metadata/<uuid>.json              # title、prompt、model、seed(若可用)、usage、hash
    staging/<job_id>/                 # 未完成輸出；不是可播放歌曲
    trash/                            # 明確刪除時先移入，可復原
  ui/music_player/                    # app 內建的專用播放器資產
    index.html                        # 固定入口，不由 agent 生成或替換
    player.js                         # 曲庫、播放控制與實際狀態回報
    player.css
  agent_workspace/tools/
    music_tool.py                     # 薄 wrapper；實際實作由 app 管理
```

選擇 SQLite 是因 app 和工具可由不同 process 呼叫；交易與唯一約束比多方直接改 JSON index 容易維持一致。完整 prompt、response ID、job error 留在 private library；播放器透過專用本機路由取得經篩選的 manifest 與依 `track_id` 定位的音訊，不直接把整個 library／database 當 static root。音檔保留 canonical 一份，避免為播放器重複複製；曲庫不是臨時 whiteboard asset，不可在換白板時被刪除。

每筆 track 最少保存：`track_id`、`title`、`created_at`、`model`、`provider_version`、`prompt`、`requested_genre_ids`、`genre_ids`、`style_notes`、`tags`、`lyrics_requested`、`lyrics_verified`、`duration_seconds`、`sample_rate`、`channels`、`mime_type`、`relative_audio_path`、`sha256`、`byte_size`、`generation_elapsed_ms`、`response_id`、`estimated_cost_usd`、`review_status`。風格欄位使用穩定 ID 的清單，不用單一 `genre` 字串。未驗證的歌詞不能標記為「符合」；創作要求與實際分類分開保存，初始分類可標記為暫定，使用者可依試聽更正，不宣稱模型必然精確遵守所選風格。

metadata sidecar 用來備份／重建；以 DB transaction 為主、檔案 atomic rename 為輔。啟動掃描修復「音檔已完成、DB 尚未更新」的中斷狀態，遺失音檔標記 missing，不偷偷重生成或從曲庫隱藏。所有成功生成且經此 app 接入的音樂均保留，失敗 job 另列；無法自動知道外部工具或 Gemini 網站曾產生的所有音樂，若要納入提供明確 import。

### 音樂生成生命週期

`queued → running → validating → completed`，異常分為 `failed`、`cancelled`、`unknown_remote_result`。

- 模型固定 `lyria-3.5`，使用者選擇的是音樂風格而非模型；UI 不提供 Clip 捷徑，預算／權限不足時說明原因，不能自動換模型。舊 Clip 試聽曲可保留為歷史音樂，不再新增。
- 一次只跑一個 paid music job，與對話 TTS 的 queue 分離；用 background worker，不能卡 Tk UI 或語音輸出。
- 呼叫 `subprocess.Popen([absolute_cli, "music", "-f", prompt_file, ...])`、`shell=False`、`CREATE_NO_WINDOW`、`--no-interactive`；key 只放子行程 env，禁止 `--api-key <secret>`、debug dump 和前端傳遞。
- CLI 版本和 archive checksum 可重現；提供設定頁診斷「找不到 CLI／版本不符／缺 key」。先以現有 `gemini` credential resolver 統一讀取，不另存第二份金鑰。
- 每個 job 使用獨立 UUID 路徑，避免 `--out` 覆寫既有歌曲；收到 `completed` 還需檢查檔案存在、可解碼、長度／大小上限及非靜音。
- 生成 timeout 建議先 180 秒、整個 job 210 秒，可設定；本次最快／最慢不是 timeout 的 SLA。不要顯示虛構百分比，僅呈現排隊／生成／整理檔案／完成。
- 取消會終止所擁有的 CLI process tree，清掉半成品；已送達供應商的請求不保證取消計費。網路 timeout／未知結果不得盲目重試，先標記狀態，讓使用者明確重試，避免重複扣款。
- 可修正且確定沒有生成的錯誤才有限重試；401／403 提示權限，402 提示 billing，429 依 retry-after 延後，保留不含憑證的錯誤分類。
- 設定每日生成次數／預估費用上限及磁碟容量上限；達標後保留現有歌曲可播放，停止新增，不自動刪除歷史歌曲。MVP 不自動重生「不好聽」作品。
- prompt generator 將「純音樂／人聲」、「風格」、「長度」、「拍號」、「歌詞」分欄整理，但仍需把它們標示為要求；保存 requested 與 actual duration，讓使用者可將疑似不合要求的版本標記、保留或自行重試。不能對時長／無人聲作未經驗證的保證。

## 7. 白板播放器規格與互動

MVP：顯示全部已完成歌曲，依建立時間排序；支援雙語大風格多選、多重 tags 篩選、標題搜尋。卡片顯示 title、duration、所有已標記的風格、建立時間、生成中／失敗狀態。同一首歌能屬於多種風格，搜尋結果仍只出現一次；完整選單與規則見 7C。播放提供播放／暫停、上一首／下一首、seek、volume、單曲循環；同時間只允許一首出聲。

曲庫 manifest 是資料來源，localStorage 只存選曲、播放位置、音量、排序／篩選偏好，不能當唯一歷史清單。manifest 可用 revision／輪詢更新；新增歌曲不強制 reload 或打斷正在播放的曲目。以 DOM `textContent` 顯示標題／歌詞，不能把 user prompt 直接插成 HTML。

原生 `<audio>` 的首次播放可能需要使用者操作；瀏覽器 autoplay 被阻擋時顯示「按播放開始」，同時向 agent 回傳 `needs_user_gesture`。已解鎖的同一播放器 session 可接受 agent 的播放、暫停與切歌指令，但必須取得 renderer ack 才能宣稱已套用。hide／close／切換白板會暫停，restore 保留進度並依 browser policy 等待播放手勢；不默默改掉既有 unload 行為。

既有 SPEAKING ducking 可沿用；目前不會在使用者開始說話時自動降低音樂，需實際測試麥克風回授、VAD、speaker recognition／喚醒詞誤觸發。第一版採較低預設音量，必要時新增使用者收音期間的暫停／duck 設定。此政策需接入 audio bridge，不能只改 CSS volume，也不能覆蓋使用者手動靜音。

**官方音樂播放器不參與 HTML 每日時間限制**；顯示「音樂播放器・不限 HTML 時間」，不顯示遊戲剩餘時間。agent 的選曲與播放控制列入 MVP（見 7A）；hide 後持續背景播放、遊戲與音樂同時呈現，仍列第二階段。不限 HTML 時間不會取消單次歌曲生成 timeout、付費生成預算、磁碟容量或正常關閉 app 的行為。

HTTP handler 新增 `HEAD`、單一 byte-range、`206`／`416`、`Accept-Ranges`／`Content-Range`，用分塊傳送避免整首讀入記憶體。保留既有 `resolve` 後 root containment、Windows drive／UNC／backslash 路徑攔截、CSP 及 localhost binding；API Key 不出現在 manifest／HTML／URL。不要為音樂放寬整個 `agent_workspace` 的 HTTP 存取權。

## 7A. 讓 AI agent 知道並正確使用音樂功能

原版僅在修改清單提及 `TOOLS.md` 與 wrapper；不足以保證 agent 知道何時使用、怎麼呼叫，以及如何操作播放器。本節將引導與控制契約列為必須實作、必須驗收的功能。以下命令與 schema 均為**預定契約**，目前沒有宣稱這些工具已可執行。

### 能力發現與引導載入

| 層次 | 內容與責任 |
|---|---|
| app 動態能力摘要 | 由程式檢查 wrapper／manager、CLI、key 來源與 renderer 是否就緒；注入 `music_available`、`player_available`、`contract_version`、`music_model=lyria-3.5`、`style_catalog_version`、雙語風格目錄入口、精確工具與 payload 目錄。只提供 credential 是否存在，不含 key。 |
| `agent_workspace_template/AGENTS.md` | 簡短寫明音樂創作與播放器的入口、所有風格使用 Lyria 3.5、官方播放器不限 HTML 時間；完整語法指向工具指南。一般 HTML 遊戲仍受原配額。 |
| `agent_workspace_template/TOOLS.md` | 補音樂工具命令、輸入／結果範例、付費生成與播放既有曲目的區別、成功／失敗回報、播放手勢限制，以及一般白板工具的相容操作。 |
| app 管理的 `tools/music/USAGE.md` | 版本化完整契約：參數、prompt 構造、job／command 狀態、範例、取消、錯誤與播放器操作。agent 可呼叫 `music_tool capabilities`／`--help` 查到同一版本。 |
| 對話 backend 接線 | Codex、Claude Code、OpenCode、Grok、Antigravity 均須透過各自現有 context 機制收到同一份能力摘要；首個 session 載入、重建 session 時重送，能力或契約版本改變時刷新。不能只改 template，或假設所有 backend 都會自動讀 `TOOLS.md`。 |

現有 `private_state.ensure_private_state()` 與 `bootstrap_workspace_files()` 只補缺檔，不覆寫已有私人檔案。因此要額外提供 app 管理的音樂引導與 canonical tool 路徑，讓舊 workspace 也能取得新功能。public template 補指引；既有 private `AGENTS.md`／`TOOLS.md`／`MEMORY.md` 不整份重寫。wrapper 若版本落後，能力摘要改指向可用的 canonical app 工具或回報需同步，不能讓 agent 反覆呼叫過時介面。

工具邊界也須同步說清楚：一般白板仍用 `whiteboard_tool`；`music_tool show-player` 是 app 新增的音樂專用入口，由 `WhiteboardManager.show_music` 執行，不是讓 agent 任意操控其他視窗。舊指引中的「白板只能使用 whiteboard_tool」應在 public 版本與 app 動態能力摘要中補上此專用入口的例外，避免指引彼此衝突。

能力分開判定：沒有 key／CLI 時，`music_available=false`，已保存曲庫仍可 `player_available=true`；HTML 遊戲額度則不參與這兩項可用性。實作完成前，app 不應向 agent 廣告「已能生成／控制播放」。

### Agent 的任務判斷與完整操作流程

1. 使用者要求「創作／生成一首」才建立新 paid job。要求「播放輕鬆音樂／播放剛剛那首」先查曲庫與最近工作的 `track_id`，不擅自付費重生成；找不到符合歌曲時再說明並釐清是否創作。
2. 先用 `styles` 取得與 UI 相同的雙語風格目錄，再構造 `title`、可多選的 `genre_ids`、補充細節 `style_notes`、`tags`、`instrumental`／人聲、情緒、節奏、期望長度、語言與原創歌詞等欄位；缺少非必要偏好可採合理預設，不逐項盤問。將風格目錄的英文名稱與補充說明組合進 prompt，保留 requested／actual 結果。模型從已保存的 `music.model` 取得，provider 再強制檢查為 `lyria-3.5`，agent 不傳臨時 model 來覆蓋。
3. 將 UTF-8 JSON payload 存到受控 `tool_payloads/music/`，呼叫 `generate`，取得 `job_id`。同一使用者請求保留 `request_id` 作冪等鍵，避免重送或 backend 續跑產生重複扣費。
4. `queued`／`running` 只回報「正在創作」。背景 worker 必須由 app 擁有，不能依附短命的 agent tool process；`job-status` 可查進度，app 完成事件送回原 session 的事件佇列，在適當時機通知使用者。事件需有 session／request correlation 和一次交付標記，重啟後也不重複通知或憑空開新 session。
5. 只有檔案驗證及入庫完成的 `completed` 回傳 `track_id`。依使用者要求開啟播放器、選取新曲，或僅通知已入庫；不因 renderer 尚未回報而宣稱已經播放。使用者正操作其他白板時，以通知／明確的播放要求決定是否切換，不因背景 job 完成無條件搶走畫面。
6. 播放既有歌曲先 `list`／`player-status`，以穩定 `track_id` 操作；同名且缺乏最近選曲線索時才要求選擇。控制動作綁定目前 `content_id` 與 state revision，避免舊指令操作到後來開啟的播放器。
7. 錯誤依 `status`、`reason`、`message_for_user` 處理；缺 key／CLI 提示回初始 UI，timeout／未知遠端結果不盲目重送付費生成。列出曲庫或控制本機播放不需要為每一步再次索取同一份授權。

### 預定工具介面

agent 優先使用 app 提供的精確 Python／wrapper 路徑，不自行推測各 backend 的 working directory。以下僅以預設 `agent_workspace/` 為例：

```powershell
..\venv\Scripts\python.exe tools\music_tool.py capabilities
..\venv\Scripts\python.exe tools\music_tool.py styles
..\venv\Scripts\python.exe tools\music_tool.py generate --payload tool_payloads/music/create_001.json
..\venv\Scripts\python.exe tools\music_tool.py job-status --job-id <job_id>
..\venv\Scripts\python.exe tools\music_tool.py cancel --job-id <job_id>
..\venv\Scripts\python.exe tools\music_tool.py list --genre-id jazz --genre-id hip-hop --genre-match any --limit 20
..\venv\Scripts\python.exe tools\music_tool.py show-player --track-id <track_id>
..\venv\Scripts\python.exe tools\music_tool.py player-status
..\venv\Scripts\python.exe tools\music_tool.py player-control --payload tool_payloads/music/control_001.json
```

生成 payload 範例；model 留給 app 設定與 provider 決定：

```json
{
  "request_id": "music-create-001",
  "title": "午後讀書時光",
  "genre_ids": ["hip-hop", "electronic"],
  "style_notes": "Lo-fi，讀書時可以輕鬆聽的混合風格",
  "tags": ["讀書", "放鬆"],
  "instrumental": true,
  "requested_duration_seconds": 60,
  "prompt": "溫暖電鋼琴、柔和低音與輕鼓，約 78 BPM；無歌詞、口白、人聲或哼唱。"
}
```

播放控制 payload 範例：

```json
{
  "request_id": "music-control-001",
  "content_id": "<active_music_content_id>",
  "expected_revision": "<player_state_revision>",
  "action": "play",
  "track_id": "<track_id>"
}
```

`player-control.action` 白名單為 `play`、`pause`、`next`、`previous`、`seek`、`set-volume`、`set-repeat`、`set-filter`；依 action 驗證 `position_seconds`、0–1 的 `volume`、`repeat=none|one|all`、可多選的 `genre_ids`、`genre_match=any|all` 與 `tags`。不接受 JavaScript、HTML、任意檔案路徑或 shell 命令。隱藏／恢復／關閉可沿用 `whiteboard_tool hide|restore|close --content-id`，manager 必須支援新的 music 類型。

| 工具結果 | agent 可以宣稱的事實 |
|---|---|
| `generate: queued`，附 `job_id` | 已加入創作佇列；不能說歌曲已完成 |
| `job-status: completed`，附 `track_id`、actual duration | 音檔已驗證、入庫，可供試聽；不能自行宣稱好聽或歌詞逐字正確 |
| `show-player: shown`，附 `content_id` | 已要求顯示播放器；renderer 未 ready 前不能承諾已看見畫面或出聲 |
| `player-control: accepted`，附 `command_id` | 指令已排隊；仍需 `player-status` 查到同一 command 的 ack |
| `player-status: applied`，含 `playback_state`、track、position、volume | 可依實際狀態說已播放／暫停／切換；`playing` 是播放器回報，不等於已驗證喇叭的實體聲音 |
| `needs_user_gesture` | 指示按播放器的播放鍵一次；不能說已開始播放或反覆重送來繞過 browser policy |
| `stale_content`／`stale_revision`／`renderer_unavailable`／`expired` | 刷新目前狀態，再依當前使用者要求處理；不讓過期 play 指令在之後開頁時突然生效 |

### Agent 與播放器之間的實際控制通道

`music_tool` 將經驗證的控制指令交給 `MusicPlaybackController`，由 app 的命令佇列與 UI dispatch 更新受控 renderer；跨 process 可利用既有 SQLite 增加 commands／ack 表。專用頁面透過同源 localhost 路由取得有序控制指令，回報 ready、當前 track、paused／playing／buffering、position、duration、volume、錯誤和 command ack。

所有 UI 按鈕與 agent 指令共用一份播放狀態。`play()` 的 Promise 被 browser 拒絕時必須回報原因；命令有期限、request id 和內容版本，close／切換白板會取消未執行指令。agent 讀到的狀態應有 renderer heartbeat 時間，過期則標記 unknown，而非把最後一次 `playing` 永久當成正在播放。音量使用使用者 base volume，再套用 ducking／mute，不讓 agent 調音量解除手動靜音。

只對固定音樂操作提供此橋接，保留同源檢查、session nonce、動作／參數白名單；不為所有 HTML 遊戲開放任意 Python／JS 操作介面。

### 預定加入 agent 引導的簡短核心文字

> 音樂功能以 app 本回合提供的 capabilities 為準。家人要求創作時使用 music_tool generate，所有新音樂只用設定中的 lyria-3.5；只要求播放時先找既有曲目。先保存 job_id，生成完成取得 track_id 後才說已做好。用 show-player 開啟官方播放器，用 player-control／player-status 選曲、播放、暫停、切歌、調整進度與音量，並核對 command ack。官方播放器不限 HTML 時間；一般 HTML 遊戲仍受限制。若回傳 needs_user_gesture，請家人按一次播放。不要讀取／朗讀 API key、直接改白板或曲庫資料檔，也不要用 show-html 自製頁面取代官方播放器。尚未 ready 或工具 unavailable 時，說明目前能做的事，不宣稱功能已可用。

## 7B. 官方播放器與 HTML 時間額度分離

這是使用者指定的產品行為，從第一版即生效；不需要另加播放器每日分鐘數，也不能用增加 `html_daily_minutes` 或修改用量紀錄來達成。

| 情境 | 官方 music 播放器 | 一般 HTML 遊戲／app |
|---|---|---|
| HTML 還有剩餘時間 | 可用，顯示／播放／暫停都不扣 HTML 時間 | 維持原本可見時計時 |
| HTML 額度設為 0 或已用完 | 仍可開啟、播放、hide／restore、重啟恢復 | 維持禁止開啟／恢復的規則 |
| HTML 用量檔讀寫失敗 | 不阻擋、不誤關閉播放器，曲庫仍可使用 | 原有 fail-closed 行為保留 |
| 從遊戲切至播放器 | 先結算切換前的遊戲用量，切換後不再計時 | 已用時間保留，不重設 |
| 從播放器切回遊戲 | 依遊戲剩餘時間決定能否切換；若被拒絕，保留當前播放器 | 原有限制照常套用 |
| 遊戲剩餘時間歸零／跨日 | 不因 HTML 的 tick／重置事件停止音樂 | 仍按原遊戲政策關閉／重置 |

實作策略：

1. `WhiteboardManager` 新增專用 `show_music`，產生 `content_type="music"`，入口固定為 app 的 `ui/music_player/index.html`，不接受 caller 提供 HTML 路徑或 quota-exempt flag。一般 `show-html` 不能自行聲稱 music 或取得免計時；豁免依賴專用入口與實際 first-party renderer，不單看 JSON 標籤或 app 名稱。
2. 新增獨立 `MusicPlayerRenderer` instance，可沿用 Edge embed／audio bridge 的共用程式，但其伺服器只供應 app 內建資產、受控 manifest／音檔與播放路由。不要把現有可由 agent 任意產生的 `apps/music_player/` 整個目錄當成免配額頁面。
3. `WhiteboardManager` 的 active schema、snapshot、status、get-content、hide／restore／reload／close 都需處理 music；restore 不呼叫 HTML quota gate，status 分別回報播放器可用性與遊戲 `html_quota`，不能用後者推論音樂是否可用。既有 html state 繼續按原規則，無自動升級豁免。
4. `ui/session_window.py` 的 `_render_whiteboard_state`、`_html_allowed`、`_account_budget`、`_tick_session`、renderer attach／resize／close 等流程要依內容類型分流；顯示 music 時不計時、不顯示遊戲 quota row，也不被 HTML 到期／儲存錯誤的 `stop()` 分支誤停。切換前的 HTML 用量結算仍須執行。
5. app 只因正常的 pause／hide／close／切換／程式關閉或音訊故障停止音樂；生成費用／次數與磁碟容量控制仍各自生效，均不等於播放器播放時間額度。

同步更新 public `AGENTS.md`／`TOOLS.md` 的「所有 HTML 都受限」敘述為「一般 HTML app 受限；app 官方音樂播放器另有專用入口且不限時」，app 注入的新能力摘要也須向保留舊 private 指引的 session 明確說明此差異。不要求 agent 重啟 app、更改時間紀錄或自行繞過限制。

## 7C. 兒童導向的雙語風格選單與多風格歌曲

### 首版採 12 種大風格

重點是幫小孩認識聲音、挑選創作方向，不追求音樂學分類的完整性，也不建立數百種細分流派。以下為首版預定內建的產品選單；每項同時顯示中文、英文和一句簡單說明。說明是聆聽／創作提示，不代表該類每首歌曲都必須使用相同樂器或節奏。分類可重疊，混合風格是正常情況。

| 穩定 ID | 選單名稱 | 給小孩的簡單說明 |
|---|---|---|
| `children` | 兒歌 / Children's Music | 旋律容易跟著唱，也可以邊唱邊玩。 |
| `pop` | 流行 / Pop | 聽聽容易記住的旋律，和會重複的副歌。 |
| `rock` | 搖滾 / Rock | 可以用電吉他和鼓，做出有精神的聲音。 |
| `jazz` | 爵士 / Jazz | 聽聽有趣的旋律變化，試著跟節奏輕輕擺動。 |
| `blues` | 藍調 / Blues | 像用音樂說心情，樂句也可以一問一答。 |
| `hip-hop` | 嘻哈 / Hip-Hop | 跟著鼓點和節拍，也可以加入有韻律的說唱。 |
| `electronic` | 電子 / Electronic | 用電子音色，想像太空、遊戲或跳舞的聲音。 |
| `classical` | 古典 / Classical | 聽聽鋼琴、弦樂或管弦樂，像一起說聲音的故事。 |
| `folk` | 民謠 / Folk | 試試像說故事的歌聲，搭配木吉他等樂器。 |
| `country` | 鄉村 / Country | 聽聽木吉他、提琴，想像旅行或鄉間生活。 |
| `latin` | 拉丁 / Latin | 試試有特色的打擊樂，跟著節奏動一動。 |
| `traditional` | 傳統音樂 / Traditional Music | 認識不同地方的旋律和樂器，例如古箏、二胡或笛子。 |

「全部 / All」和「未分類 / Unclassified」是另外的篩選操作，不算音樂風格；也不要把它們傳成創作的 `genre_ids`。Lo-fi、Synth-pop、華爾滋等更細的想法可放 `style_notes`／補充標籤，自由提出，但不自動增加兒童基本選單的複雜度。情緒、樂器、用途、語言、是否有人聲另作可選創作提示，不混成十幾層的風格樹。

### 空曲庫也完整顯示，兼作創作引導

- 將完整目錄內建於 `assets/music_styles.v1.json`：至少包含 `id`、`label_zh_hant`、`label_en`、`description_zh_hant`、中英搜尋 `aliases`、`sort_order`、`catalog_version`。UI、agent 的 `styles` 命令及後端驗證共用同一來源，不從曲庫目前的標籤推導選項。
- 初次開啟、沒有任何歌或某類有 0 首時，仍顯示全部 12 項及雙語名稱；0 首可標示，但不隱藏、禁用或移到難以找到的位置。可用簡單卡片／多選按鈕呈現，搭配特色說明，避免細分下拉樹。
- 支援以中文或英文搜尋選項，例如「爵士」和 `jazz` 指向同一 ID；英文大小寫、常見別名不產生重複類別。曲卡上的多個風格標籤也使用相同雙語名稱。
- 選到空類別時，顯示「目前還沒有這種音樂，可以試著創作一首」，並提供「用這些風格創作」入口，把所選風格帶入創作草稿／既有送出流程；單純選風格或篩選不會生成、播放或付費。
- 可同時挑兩種來認識混合風格，例如「爵士 / Jazz ＋ 嘻哈 / Hip-Hop」。agent 能解釋所選大風格、把英文名稱轉成音樂 prompt；不把沒有試聽過的分類描述成必然生成的聽感。

### 多風格保存與篩選規則

1. 每首歌使用 `genre_ids` 陣列，例如 `["jazz", "hip-hop"]`；SQLite 用 `track_genres(track_id, genre_id)` 多對多關聯，pair 唯一。創作要求另存 `requested_genre_ids`；不把顯示用的「爵士 / Jazz」或斜線串接字串當作資料鍵。
2. 風格可多選。預設 `genre_match="any"`，畫面用簡單文字「符合任一風格」：選爵士與嘻哈時，包含只有爵士、只有嘻哈及兩者都有的歌。
3. 當至少選兩項時，另可切為「同時具有這些風格」，對應 `genre_match="all"`：只找同時含有所選每一項的歌。不在兒童 UI 顯示 OR／AND 術語，也不需要巢狀條件編輯器。
4. 未選風格＝全部歌曲；多風格歌曲在結果與播放佇列只出現一次。風格條件再與標題搜尋、其他已選條件相交；UI 和 agent 的 `list`／`set-filter` 使用同一實作，語意一致。
5. 每個風格的首數以不同 `track_id` 計算。雙風格歌可各計入兩類，但「全部」只計一次，不能把各類數量相加當總歌數；不因任一類為 0 而移除該選項。
6. 尚無可辨識標籤的匯入歌曲歸在「未分類」，不丟掉、隱藏或猜測成單一類。舊單一 `genre`／自由文字透過已知別名映射遷移並保留原文，無法可靠對應時等待更正。重新標記可修改多個風格，不重生成音樂。
7. JSON 匯出、sidecar、manifest、localStorage 的選曲／篩選偏好及 tool payload 全程保留多選 ID。目錄未來增加或改顯示名稱時保持舊 ID，讓歷史歌曲、篩選與分享資料不失效；基本選單不因 agent 隨口提出子流派而自行膨脹。

本節是規劃需求與首版選項草案，尚未新增正式播放器或風格目錄資產；實作時依此表建立共用 JSON，無須為了風格選單查詢 Google 模型列表或另外呼叫付費生成。

## 8. 預計檔案修改清單

| 檔案／位置 | 預計變更 |
|---|---|
| 新增 `core/music_manager.py` | 曲庫、SQLite、job 狀態、atomic publish、匯出與容量管理；風格多對多關聯與共用 any／all 篩選 |
| 新增 `utils/gemini_music.py` | 可替換 provider 介面與 CLI subprocess adapter；輸出 schema 驗證及去除敏感資訊 |
| 新增 `tools/music_tool.py` | `capabilities`／`styles`／`generate`／`job-status`／`cancel`／`list`／`show-player`／`player-status`／`player-control`；另補 import／rename／retag；共用風格 IDs、結構化結果與冪等 request id |
| 新增 `agent_workspace_template/tools/music_tool.py` | 與既有 whiteboard／schedule 類似的穩定 wrapper，不內含 secret |
| 新增 `ui/music_player/` 與 `ui/music_player_renderer.py` | app 內建播放器與專用 renderer；12 種雙語大風格、特色提示、多選、0 首仍可用與創作引導；不是 agent 可任意產生的免額度 HTML |
| 新增 `assets/music_styles.v1.json` 及共用 loader | 首版 12 種兒童導向大風格、穩定 IDs、中英名稱、說明與別名，供 UI／agent／後端共用；不依目前曲庫或 Google 模型列表產生 |
| 新增 `core/music_playback.py` | UI／agent 共用播放狀態、command queue、ack、heartbeat、逾期／過時命令處理 |
| `core/whiteboard_manager.py` | 新增專用 `show_music` 與 music state；restore／reload／status／snapshot 分流，避免沿用 `show_html` 的配額 gate |
| `ui/html_whiteboard.py`、`ui/embedded_html.py` | 共用 Edge embed／audio bridge；音訊 HEAD／Range／streaming response，供專用 renderer 使用；保持橋接、CSP 與一般 HTML 額度 |
| `ui/session_window.py`、必要的 `main_window.py` | 曲庫入口、job 完成事件與控制 ack；HTML 計時／到期關閉／quota error 依內容分流，music 不計時且不被誤停 |
| `config.default.json`、`config.example.json`、`config.py`／settings schema | 新增 music enabled/provider/model/CLI path/job timeout/容量與每日上限，保持 layered config |
| `private_state.py`、`llm/workspace_context.py` | 建立 library、補穩定 wrapper 與版本化工具指南、組合動態 music capabilities；保留既有家庭檔案 |
| `core/assistant.py`、`llm/client_factory.py` 及各 backend 的 context 路徑 | 注入同一能力摘要與音樂引導；重建 session／契約版本改變時刷新，catalog-only session 不載入家庭／音樂操作上下文 |
| `.gitignore`、`scripts/pre_git_audit.ps1` | 排除 library、staging、database／sidecars／生成媒體，僅保留 README placeholder |
| public `AGENTS.md`／`TOOLS.md`、版本化 `tools/music/USAGE.md`、`docs/html_whiteboard.md`、新 music 使用指南 | 創作／播放判斷、命令與結果、操作示例、首次播放、曲庫備份、官方播放器不限 HTML 時間與遊戲限制的差異 |
| `tests/` | provider contract、曲庫復原、HTTP Range、各 backend 引導、job／player ack、雙語固定目錄與多風格篩選、ducking／HTML 配額隔離的回歸 |

private workspace 的 `AGENTS.md` 和既有記憶不重寫。public template 更新不會自動覆蓋既有 private tools；實作時需要版本化 app 引導、canonical 入口與工具同步檢查（7A），避免只有新安裝可用。新增的程式引導必須以真實 capabilities 為準，不能在工具尚未交付時讓 agent 宣稱可用。

TTS 此刻不增加 CLI backend。若另做延遲改善，優先測 current engine 的 HTTP client reuse、首段字數及 request interval，在不破壞音色／限流前提下做逐項對照；`gemini-3.8-flash-lite-tts` 是可另測的模型選項，但本次沒有量測其品質和速度，不承諾會改善。

## 9. 分階段實作與驗收

1. **試聽確認（已完成）**：使用者接受初輪三首並指定所有新音樂只用 `lyria-3.5`；這個選擇是實作約束，不再要求重複確認。
2. **曲庫核心、工具與引導**：完成 job／SQLite／成功音檔保存與清單，以及 capabilities／命令契約和所有 backend 的引導注入。重開後仍可列出全部歌曲；並行要求不互相覆寫；生成取消／timeout 不產生假成功。
3. **白板播放器與 agent 控制**：app 內建的 music 內容、專用 renderer、12 種雙語大風格與創作提示、多風格篩選、搜尋／單首播放／seek，以及 agent play／pause／選曲／volume 與 ack。此階段即免 HTML 時間，不延到第二階段。先匯入本次生成檔案，UI 測試不反覆消耗付費生成。
4. **整合與回歸**：實際 Windows／Edge 與音效裝置測播放、控制 ack、duck／mute、hide／restore、HTML 配額分流及跨 backend 端到端流程；通過後再啟用使用者日常生成。

必要驗收案例：

- 所有測試音樂匯入後，關閉／重開 app，清單數量不變、風格篩選正確，沒有重生成；新 generation 的 model 一律是 `lyria-3.5`。
- 全新空曲庫及部分類別有 0 首時，仍完整顯示首版 12 種風格的中文、英文與特色說明，均可選擇；不出現大量子流派，也不隨匯入的自由標籤自行擴張基本選單。
- 用測試歌曲 A=`[jazz, hip-hop]`、B=`[jazz]`、C=`[hip-hop]`、D=`[rock]`、E=`[]` 驗證：爵士篩選得到 A、B；爵士＋嘻哈的 any 得到 A、B、C，各一筆；all 只得到 A；不選風格得到全部五首；未分類只得到 E。全部數量為 5，不能把各風格數量相加當總數。
- 用「爵士」與 `Jazz` 搜尋均找到同一選項；曲卡、生成 payload、manifest、sidecar、備份重建、重新載入與 agent 查詢保留同一首歌的全部風格 IDs，不退化為單選字串。
- 選到 0 首的「流行 / Pop」時有空狀態與創作入口，能帶入 `genre_ids=[pop]`；只點選風格／篩選不會觸發生成。UI 與 `music_tool styles` 使用相同目錄，`list`／`set-filter` 的 any／all 結果一致。
- 生成另一首後既有播放不中斷、清單能更新；DB 和 manifest revision 一致。
- 401／402／403／429／5xx／network timeout、缺少檔案、損毀 MP3、磁碟已滿、CLI 版本錯誤、取消、process 遺留均有可理解結果。
- 歌曲 title／prompt 含中文、空白、引號、HTML 或 PowerShell 字元，沒有 shell injection 或 HTML injection。
- 首次手動播放、拖曳到中段／結尾、切歌、循環、volume、mute、TTS ducking 與 hide／restore 均符合規格。
- 音樂播放或暫停持續超過 30 分鐘，HTML `used_seconds` 不增加；HTML 額度為 0／用完／用量讀寫故障，仍能開啟與恢復官方播放器，不被 `_tick_session`／quota exception 的 stop 分支誤關閉。
- 遊戲 → 音樂只結算切換前的遊戲時間；音樂 → 遊戲仍受原 quota gate；拒絕切換時保留播放器。午夜、睡眠／喚醒、重開 app 與 quota error 復原不導致誤計時或音樂誤停。
- 普通 HTML 即使叫 `music_player`、複製播放器外觀或傳 `content_type=music`／`quota_exempt=true`，仍不能經 `show-html` 取得免額度；不改 HTML 用量檔或把每日額度設成無限。
- 五個對話 backend 均驗證收到目前可用的音樂能力與指南；保留舊 private `AGENTS.md`／`TOOLS.md` 的安裝也能取得正確入口，不重寫家庭記憶。
- 「創作一首無人聲讀書音樂」依序得到 job、completed、track 與可試聽的播放器；重送同一 request id 不重複付費。正常對話不可被背景生成卡住，完成通知一次送回原 session。
- 「播剛剛那首／暫停／下一首／音量小一點／跳到 20 秒」只控制現有歌曲，不呼叫生成；UI／agent 的 track、position、volume 與 command ack 一致。
- 模擬 browser 拒絕 autoplay、renderer 未附著、heartbeat 過期、command timeout、content id／revision 過時；agent 不把 `accepted` 說成已播放、不聲稱憑空聽到音樂，也不讓過期命令稍後突然生效。
- 同源 media `HEAD`／`Range` 可用；非法範圍回 416；越界／UNC／symlink escape 仍拒絕；既有遊戲與 input bridge 不退步。
- 在正式有程式變更時執行 `ai_voice_assistant/venv/Scripts/python.exe -m pytest -q`，Windows UI／音訊另做真人測試。單元測試不能取代真實瀏覽器音訊驗收。

## 10. 產物、重跑與限制

### 本次交付

- 本規劃書與文件索引；7A 包含 agent 引導／工具與播放器控制契約，7B 明定官方播放器不限 HTML 時間，7C 定義 12 種兒童導向雙語風格、空曲庫創作引導與多風格篩選。
- 可重跑的 opt-in probe script；不讀歷史私人音檔，使用固定原創測試文字及 prompts。
- 本機 ignored folder 內的 CLI／release source、checksum、24 次 TTS 音檔與原始 metrics、五首 MP3、prompt、blind reviews、`listen.html`。
- 可納入 Git 的[去敏證據 JSON](gemini_api_cli_probe_2026-10-26.json)：完整 24 次量測、五首音樂 metadata／prompt、五份模型盲聽與使用者選型；不含 API Key、private config 全文、絕對路徑／response IDs 或音訊 base64。

### 重跑

於 repo root 使用 PowerShell；`--run` 會實際呼叫付費 API，新的 run 必須使用新的 output 目錄。probe 已依使用者偏好更新，新 run 的三首音樂全用 `lyria-3.5`；初輪 Clip 是歷史比較資料，其原 prompt 已保存在本輪結果中。對已完成的 music／review 再執行會跳過成功項目，避免重複付費：

```powershell
.\ai_voice_assistant\venv\Scripts\python.exe scripts/gemini_api_capability_probe.py --run --phase all --cli tool_payloads/gemini_api_eval_20261026/cli/gemini-api.exe --output tool_payloads/gemini_api_eval_20261026/run2 --repeats 3
.\ai_voice_assistant\venv\Scripts\python.exe scripts/gemini_api_capability_probe.py --run --phase review --cli tool_payloads/gemini_api_eval_20261026/cli/gemini-api.exe --output tool_payloads/gemini_api_eval_20261026/run2
```

只重新開試聽頁，無付費 API：

```powershell
.\ai_voice_assistant\venv\Scripts\python.exe -m http.server 8765 --bind 127.0.0.1 --directory tool_payloads/gemini_api_eval_20261026/run1
```

### 驗證界線

原研究階段沒有把正式音樂播放器接入白板；其後實作與驗收見末章。研究階段沒有更動 Google subscription／Billing、config.local.json、私人記憶，或提交／推送 commit。試聽 HTML 是獨立本機驗證頁，不代表正式 app 已有曲庫功能。

本次驗證：

- TTS 24／24、music 5／5、blind review 5／5 成功，保留慢樣本及不合 prompt 的疑點。
- 所有 29 個生成音檔已完整解碼，非靜音；五首 music 均為 44.1 kHz stereo。
- 試聽頁 HTTP 200、五個 audio controls，MP3 Content-Type／Content-Length 可讀；初輪三首另有使用者真人試聽回饋。
- probe 的 Python AST 語法檢查通過；Windows stdout 改為 UTF-8，避免 cp950 遇到罕見中文字而中斷。首次 blind review 在檔案已寫入後遇到 stdout encoding error，補上 resume 後沿用該成功結果，沒有為印出文字重新付費生成。
- Markdown／Python／JSON strict UTF-8 解碼成功，replacement char count 0；交付檔案未包含本機 API Key、證據沒有絕對 Windows 路徑或音訊 base64。
- `git diff --check` 通過，`pre_git_audit.ps1` 回報 `[OK]`；音檔、CLI binary 與完整 private 原始結果均在 Git ignored 的 `tool_payloads/`。
- 原研究階段沒有更改正式 runtime，當時未跑整套 pytest；其後正式實作已另跑回歸及原生 UI 驗證，結果見第 11 章與實作紀錄。


## 11. 正式實作完成與驗收（2026-10-26）

### 功能落地

- `core/music_manager.py` 與 `music_worker.py`：SQLite 短 transaction、單 worker lease、request_id 去重、背景佇列、取消、未知結果不自動付費重試、原子檔案發布與崩潰恢復。每日預設 10 次／US$0.80，總容量 2 GiB。
- `utils/gemini_music.py`：CLI 固定 `lyria-3.5`、prompt file、store:false、key 僅 child env、Windows job 管理與限時；TTS 不改走 CLI。
- `ui/music_player/` 與專屬 renderer：暖白木色與霧藍色、黑膠歌曲卡片、12 種雙語風格介紹、搜尋與 ANY／ALL、創作／分類更正表單、單一播放列、手機排版。
- 專用 `content_type=music` 只載入 app 固定入口，不傳任意檔案免計時 flag。HTML 額度停用、用完、紀錄故障皆不阻擋，也不扣音樂秒數；遊戲仍走原本 gate。
- `tools/music_tool.py`、`tools/music/USAGE.md`、`llm/music_context.py`：五種 backend 的一般回合均有 app 引導與絕對入口；既有 private AGENTS／TOOLS 不覆寫。生成要查 completed；播放要查 command ack 與 playing，不把 accepted 誤說成成功播放。
- 曲庫、暫存、SQLite 與音檔 Git ignored，audit 新增 music placeholder；無 key 可聽已有歌曲。隱藏／切換／重開暫停，說話與收音自動 duck。

### 真實驗收與經驗

原先接受的五首已匯入永久曲庫，新驗收曲〈雨後花園的小探險〉由 Lyria 3.5 成功生成，耗時 89.26 秒，指定約 45 秒但實際 60.839 秒，MP3 1,466,266 bytes。已完整解碼並由原生白板回報播放中；agent 指令收到同一 command_id 的 applied。正式曲庫共 6 首。新曲的樂器／人聲品質仍留待真人試聽，沒有把可解碼冒充品質合格。

初次驗收發現 cancellation interface 缺 wait()，如實保留 unknown_remote_result，未自動重試；修正並加入 provider 邊界回歸後，另一次受控驗收成功。費用保守按兩次提交最多 US$0.16 規劃，未查 Billing 實付。這個經驗已落實為「版本／key 前置失敗與遠端結果未知分開」「不自動重送」「Event 相容性測試」。

最終一般回歸 1285 passed、36 skipped；啟用原生 UI 的 UI／CLI／session 組合 69 passed，另重跑 music 原生案例 2 passed。另驗證 1024×900 桌面、390×844 窄版無橫向溢出且保留英文；pop+electronic 的 ANY 得 3 首、ALL 得 1 首。隔離 UI 的創作流程使用錄製音訊替身，避免再為每次介面測試付費。最終全套測試與 audit、檔案對照、實際限制見[完整實作與驗收紀錄](music_implementation_2026-10-26.md)。

使用方式、預設限制、備份、錯誤處理、agent 流程見[音樂指南](music.md)。
