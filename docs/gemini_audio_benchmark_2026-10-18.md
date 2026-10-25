# Gemini 語音 API 實測：2026-10-18

本輪完成真實 STT／TTS API 比較、可回聽的本機比較頁，以及初始 UI 的 Google API key 輸入／立即儲存／刪除。後續已完成正式 Gemini backend、詳細設定與音色選擇，見 [使用指南](gemini_audio_setup.md)；下列數字保留本輪 benchmark 的量測條件。

目前建議維持 Groq STT、Edge TTS 為原本使用組合，Gemini 已可手動選用。這次 STT 沒有速度優勢，且直接送入無人聲音訊會產生虛構文字；正式 adapter 已加入人聲與異常輸出檢查。TTS 已確認可串流生成，多音色的偏好需要實際試聽。

## 語音辨識速度

從使用者授權的歷史 archive 取 20 段不同長度的輸入音檔，另生成 4 段無人聲樣本。每段對每個 backend 跑 5 輪，共 240 次轉錄操作；Groq confidence gate 額外請求也計入，共 294 次 network attempts。

歷史音檔各長度區間各 5 段，範圍 2.048–45.888 秒。每個 paired clip 使用相同的 mono 16 kHz PCM16 音訊內容，模型順序交錯，以固定 seed 隨機化。

下表使用歷史輸入音檔的成功操作，包含編碼、連線、API、Groq gate 重試與解析；不包含刻意限速的 scheduler wait，也不包含 VAD、LLM 或播放。

| STT | 設定 | 成功操作 P50 | 成功操作 P95 |
| --- | --- | --- | --- |
| Groq | `whisper-large-v3`，現行 confidence gate | 1.019 秒 | 1.965 秒 |
| Gemini | `gemini-3.8-flash`，`thinking_level=low` | 2.918 秒 | 4.103 秒 |

以 clip 的多輪中位數配對，20 段都是 Gemini 較慢；差值的中位數約 1.785 秒。以 clip 為單位 bootstrap 的 95% 區間約為 1.379–1.984 秒，只描述這 20 段與這次網路／帳戶條件，不代表所有使用情境。

| 歷史輸入長度 | Groq P50 | Gemini P50 |
| --- | --- | --- |
| ≤4 秒 | 1.044 秒 | 2.510 秒 |
| >4–8 秒 | 0.968 秒 | 2.707 秒 |
| >8–15 秒 | 0.809 秒 | 2.837 秒 |
| >15–60 秒 | 1.602 秒 | 3.506 秒 |

Gemini 所有已取得 usage 的 STT 紀錄，thought tokens 都是 0。這不代表支援 `off`；本次仍傳入官方支援的最低 `low`。[模型與 thinking 支援](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)

### 限流與缺少文字回應

- Groq：120 次操作，115 次未出現 HTTP error，5 次 HTTP 429；gate 共增加 54 次請求。
- Gemini：120 次操作，118 次通過文字回應解析；另外 2 次是 HTTP 成功後沒有 text output block，保留為 `missing_text_output`，不等同 HTTP 服務故障。
- Groq 密集呼叫遇到 429 後暫停並續跑，後續每段 Groq 操作間隔至少 8 秒；刻意等待時間不計入上表。錯誤紀錄沒有刪除或當成成功。
- P50／P95 是成功操作的條件統計，必須搭配上述錯誤數一起看。每次 `transcribe()` 建立 client，與現有 Groq app 的生命週期一致，不能將 TLS／連線成本全解讀成模型計算時間。

## 準確度能確認與不能確認的部分

使用者已確認歷史 `.txt` 沒有人工校對，不能作為 ground truth；其中 8 段的舊文字是空白或「無法辨識」。因此本輪沒有可信的真人 CER／WER 準確率排名。

原始 metrics 的 `historical_reference_cer_NOT_accuracy` 只表示與舊 ASR 的文字距離，不能解讀成真正錯字率。兩個模型給出不同文字，可能是補回舊模型漏掉的內容，也可能是幻覺，必須回聽確認。

### 已知無人聲樣本

這組直接呼叫模型，繞過 app VAD，用來觀察模型本身；不是產品實際誤觸發率。4 段不同樣本各跑 5 次，不是 20 個獨立環境。

| 2 秒合成樣本 | Groq 非空文字／5 次 | Gemini 非空文字／5 次 |
| --- | --- | --- |
| 完全靜音 | 0 | 5 |
| 低幅度隨機噪音 | 0 | 4（另 1 次缺少 text block） |
| 60 Hz hum | 0（另 1 次 429） | 5 |
| 短促 clicks | 5 | 5 |

Groq 的 5 次非空回應都是「聲音雜亂，系統無法辨識」類提示，不是可執行的語音內容。Gemini 的非空回應則包含憑空出現的字詞或句子，總計 19／20 次；完全靜音也沒有穩定回空白。

另有一段 27.04 秒的歷史輸入，Gemini 某輪產生 2,005 個字元的大量重複內容。回聽頁已標記這個長度異常候選，未將它當正確轉錄。

文字正規化後（NFKC、移除標點／空白、英文小寫），20 段中五輪成功且全文一致的片段為 Groq 15 段、Gemini 3 段。這是輸出穩定性，仍不是準確率；失敗導致不足五輪的片段不計為一致。

正式接入前，Gemini STT 必須維持 VAD、辨識結果異常檢查，並攔截截斷／重複輸出。單純加入「沒有語音回空白」的 prompt 不足以取代這些保護；也不能用過高音量門檻犧牲真正小聲的人聲。

## 語音輸出

使用固定的 10 段公開測試文字，每段每個 backend 成功生成 3 次。涵蓋短回覆、數字、中英、問句與長段；Edge 共 30 次成功，Gemini 共 34 次 attempts、30 次成功，另 4 次為 429。限流紀錄保留，恢復後只補測失敗項目。

- Edge：`zh-TW-HsiaoChenNeural`，`rate=+0%`、`volume=+0%`，使用專案現有 progressive decode。
- Gemini：`gemini-3.8-flash-tts`，voice `Kore`，style 指定自然溫暖的台灣華語，串流 `audio/l16`、mono 24 kHz。
- 計時終點是程式已解碼的 PCM，沒有送進音效卡；非零 sample 不等同實際喇叭發聲。

| TTS 成功操作 | 首個非零 PCM P50 | 首個非零 PCM P95 | 完整合成 P50 | 完整合成 P95 |
| --- | --- | --- | --- | --- |
| Edge | 0.666 秒 | 2.171 秒 | 1.004 秒 | 2.561 秒 |
| Gemini Kore | 1.303 秒 | 1.549 秒 | 2.589 秒 | 3.911 秒 |

本次 Edge 的典型首段較快，Gemini 的首段尾端分布較集中；只有 30 個成功操作，不能推論所有網路／負載條件。完整生成時間也受兩個音色的朗讀時長影響：成功音訊總長分別約 181.3 秒、165.6 秒。

另外成功產生 `Puck`、`Charon`、`Zephyr` 的相同短句預覽，可與 `Kore` 回聽比較。沒有代替使用者宣稱哪個音色更自然；自然度、口音、漏字／加字與英文發音仍需聽音確認。[官方音色與串流格式](https://ai.google.dev/gemini-api/docs/speech-generation)

## 資料、費用與重現

本機 private 資料均位於 `ai_voice_assistant/logs/audio_benchmark/`：

- `gemini_groq_20261018/`：manifest、SHA-256、設定、逐次 JSONL、summary、配對分析、`review.html`。
- `gemini_tts_20261018/`：逐次紀錄、設定、summary、各次 PCM WAV。
- `gemini_tts_voice_Puck/`、`gemini_tts_voice_Charon/`、`gemini_tts_voice_Zephyr/`：音色預覽。
- `gemini_smoke_20261018/`：初始 STT 與完整 WAV TTS 的連線驗證。

回聽頁引用原始音檔，不上傳或複製整個 archive；可手動填寫並匯出已校對的 reference。生成頁面只含本機音訊路徑，不使用外部 scripts 或服務。請保留為私人資料。

已記錄操作的合計估價約 USD 0.15，其中 Gemini STT 約 $0.0385、主要 Gemini TTS 約 $0.0375、Groq 約 $0.0719，另有少量音色預覽。這不是帳單：Groq 失敗請求的計費、未取得 usage 的回應、smoke 與中止中的請求不完全包含在此估價。

估價使用查核當日 Standard 價格；Gemini 2026 年底前有價格優惠，不能把本次價格永久寫死為未來費率。Thinking 與 output 的 token 計數分開，兩者皆需依官方費率計費。[價格](https://ai.google.dev/gemini-api/docs/pricing)、[Thinking 計費](https://ai.google.dev/gemini-api/docs/thinking)

重現指令（會真的呼叫 API）：

```powershell
cd ai_voice_assistant
# 未加 --run 時只準備 manifest，不呼叫付費 API。
.\venv\Scripts\python.exe -X utf8 tools/benchmark_audio_backends.py --run --output logs/audio_benchmark/new_stt_run --min-groq-interval 8
.\venv\Scripts\python.exe -X utf8 tools/benchmark_gemini_tts.py --run --output logs/audio_benchmark/new_tts_run --min-gemini-interval 8
.\venv\Scripts\python.exe -X utf8 tools/audio_benchmark_review.py logs/audio_benchmark/new_stt_run --tts-dir logs/audio_benchmark/new_tts_run
```

## Google API key UI 與驗證

初始設定第二步「輸入與輸出」新增 Google API key 卡片，支援：遮罩輸入、顯示新輸入、立即儲存、立即刪除本機 key。它不預填舊 key、不在摘要顯示值，寫入失敗保留舊設定。

實際 key 已從使用者提供的桌面檔讀取並保存到 gitignored `config.local.json`；桌面檔日後移除不影響設定。刪除本機 key 不會改動 Windows 環境變數，使用環境變數時 UI 會明示來源。

此份 benchmark 完成時，完整 pytest 為 999 passed、11 skipped；新增串流測試後，受影響的 API／key／config／session 測試為 45 passed、1 skipped，原生 UI 與新測試合計 14 passed。後續正式整合驗證更新於使用指南；未選用 Gemini 的正式語音流程維持原設定。

後續已完成正式 backend／音色 UI 與軟體取消、mute／generation lifecycle 測試；本輪 API 數字仍不能推論真實麥克風到喇叭的端到端延遲或真人人工 ground truth 準確率。
