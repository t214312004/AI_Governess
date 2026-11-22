# Breeze-ASR-25 GPU 實際錄音測試

日期：2026-11-17。所有 ASR 推論均確認為 `cuda / int8_float16`，使用 RTX 5060 Laptop GPU（8151 MiB VRAM）；沒有 CPU ASR fallback，也沒有呼叫雲端辨識。GPU 限定指模型推論；讀檔、特徵處理與報表運算仍有 CPU 工作。

**結論：這台 GPU 能穩定執行 Breeze。暫時維持 `auto / beam_size=5` 的試用預設；目前證據不足以將它改成強制 `en`，或以速度理由改成 beam 1。這次完成的是可重現的 GPU 執行、延遲與輸出差異測試，尚非人工正確率驗收。**

可核聽原音、搜尋文字並對照六組輸出的 [本機完整對照頁](../ai_voice_assistant/asr_eval_outputs/breeze_gpu_20261117_195829/combined/comparison.html)。逐字稿與音檔連結保存在 Git 忽略的私人測試目錄，本文件只記錄彙總結果。

## 測試資料與方法

- 盤點現有 `whisper_audio_archive/`：645 段，總長 98.74 分鐘，均為 16 kHz WAV。
- 固定挑選 40 段，共 518.272 秒（8 分 38 秒）；單段 1.856–57.856 秒，中位長度 6.528 秒。
- 選樣標記：歷史含英文字 10 段、近期 6 段、短句 6 段、長句 4 段、歷史空白 4 段、歷史雜訊標記 4 段、其他 6 段。這是分層診斷樣本，不是全錄音庫的隨機母體估計。
- 每組設定各跑兩輪，共 **480 次正式計時推論**；載入與另外的暖機推論不納入統計。
- 模型依序在獨立 process 載入，同一時間只有一個測試模型使用 GPU。每個 worker 檢查 native `device == cuda` 與 `compute_type == int8_float16`。
- 各模式使用相同錄音；第二輪重新排序，Breeze 的三種語言設定交錯執行。beam 1 使用第一批 manifest，並核對相同檔名與 SHA-256。測試後 40 段音檔 hash 仍與測試前一致。
- 使用既有斷句後的錄音，`vad_filter=False`，保留 faster-whisper 預設 temperature fallback、`best_of=5`、timestamps 與前文條件設定。
- 時間包含 native ASR 的特徵擷取、語言偵測與解碼，不包含音檔讀取、VAD、LLM、TTS 或應用層提示回聲重試。原始與既有文字過濾後的結果分開保存。
- 舊 `.txt` 是當時 ASR 產生的文字，沒有可驗證的人工校對標記或可靠的歷史模型來源資訊。因此沒有將它當成正解，也沒有報告 CER、WER 或準確率。

軟體環境：Python 3.14.4、faster-whisper 1.2.1、CTranslate2 4.7.1、NVIDIA driver 621.14。使用原有環境，沒有替換 PyTorch 或安裝 CUDA。

## 模型來源

| 模型 | 本機來源／revision | 模型檔大小 |
|---|---|---:|
| Breeze-ASR-25 CT2 INT8 | `shdennlin/breeze-asr-25-ct2`，`70660216b01a6f6b7b8c5690767a4763df61755f`，`int8_float16/` | 1,551,140,573 bytes |
| Whisper-large-v1 CT2 | 已快取的 `Systran/faster-whisper-large-v1`，`b07c8d4be0be90092aa01a29c975077acb8d15c9` | 3,086,912,962 bytes |

兩者的實際執行精度都確認為 INT8 / FP16；這不是完整未量化 FP16 模型的比較。模型檔 SHA-256 另存於私人結果中的 `model_checksums.json`。

Whisper-large-v1 是專案既有本地模型。此比較**不能代表目前 Groq 的 Whisper-large-v3 服務表現**，也沒有從這次資料推導 Breeze 勝過 Groq 的結論。

## 排除載入與暖機後的時間

每列均為 40 段 × 2 輪，共 80 筆。RTF 為總辨識秒數除以總音訊秒數，越低越快；p95 使用線性插值。

| 設定 | p50 秒 | p95 秒 | RTF |
|---|---:|---:|---:|
| Breeze auto / beam 5 | 1.112 | 7.686 | 0.171 |
| Breeze auto / beam 1 | 1.063 | 6.637 | 0.158 |
| Breeze zh / beam 5 | 0.776 | 4.548 | 0.145 |
| Breeze en / beam 5 | 1.046 | 6.035 | 0.154 |
| Whisper-v1 zh + 繁體提示 / beam 5 | 0.589 | 4.270 | 0.089 |
| Whisper-v1 auto + 空提示 / beam 5 | 1.065 | 4.940 | 0.174 |

不能把較快的一列直接當成辨識品質較好：輸出字數、是否產生提示回聲、雜訊片段與 fallback 都會影響時間。

若只看 3–15 秒的錄音，各列為 19 段 × 2 輪：

| 設定 | p50 秒 | p95 秒 |
|---|---:|---:|
| Breeze auto / beam 5 | 0.715 | 3.357 |
| Breeze auto / beam 1 | 0.667 | 2.674 |
| Whisper-v1 zh + 提示 / beam 5 | 0.550 | 0.871 |
| Whisper-v1 auto / beam 5 | 0.733 | 1.109 |

Breeze 的一般短句中位延遲可用，但 p95 仍高於初步提出的 2 秒目標；降低 beam 並未完全解決長尾。這些只是 STT 時間，完整互動還會加上斷句、LLM 與 TTS 等待。

## 解碼語言的實際差異

Breeze `auto / beam 5` 的 80 次結果全部偵測為 `zh`。去除標點、空白、大小寫及全形差異後：

| 與 Breeze auto / beam 5 對照 | 全部相同文字 | 兩邊都未觸發溫度重試時相同文字 |
|---|---:|---:|
| 強制 zh / beam 5 | 72 / 80 | **64 / 64** |
| 強制 en / beam 5 | 49 / 80 | **44 / 64** |

`auto` 與 `zh` 的差異集中於會觸發溫度重試的片段，不能全歸因於 language token。強制 `en` 在沒有溫度重試的對照中也會改變文字；沒有人工正解，無法判定那些改動普遍較好或較差。

因此保留 `auto` 是目前較合理的預設。強制 `zh` 在這批華語為主的音訊上較快，但這批沒有足夠純英語樣本，不能由此推導它適合所有輸入。也不能因模型的某個設定檔出現 `en` token，就將現有 CT2 路徑改成強制 `en`。

## 搜尋寬度與重試

beam 1 相對 beam 5 的整體中位時間只改善約 4.4%。兩組在相同錄音、相同輪次的 80 個文字對照中，只有 41 個正規化後完全相同；不能把這種差異直接當成錯誤率，但足以說明這不是完全不影響輸出的加速選項。

同一設定兩輪輸出一致的片段數：auto / beam 5 為 38 / 40，auto / beam 1 為 33 / 40。兩者分別有 16 / 80、17 / 80 次執行包含溫度重試。初版繼續使用 beam 5，beam 1 保留為可自行核聽的速度選項。

本次保留 `best_of=5`；非零溫度重試時，faster-whisper 會切換成取樣候選流程。因此 beam 1 不代表所有重試都只保留一個候選，也不保證 VRAM 峰值必然降低。[對應實作](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py#L1433)

## 輸出品質目前可以與不能判斷的事

選樣中標記為歷史空白／雜訊的 8 段，Breeze auto / beam 5 在兩輪共 16 次均產生非空文字。這些音檔不是數位全零訊號；是否包含實際人聲、背景播放或幻覺，仍需核聽。不能因舊 ASR 沒有文字，就把新的文字一律判錯；也不能把有文字一律判成功。

Whisper-v1 `zh + 提示` 的 80 次輸出中，有 20 次會被現有提示回聲／雜訊文字規則過濾；Breeze 沒有觸發相同規則。這說明現有文字過濾規則不一定能涵蓋 Breeze 的失敗樣態，不構成 Breeze 誤辨識較少的證據。

完整對照頁保留原始文字與錄音；原始及過濾後文字、segments、no-speech probability、log probability 和 temperature 均可在 JSONL 查核。不同模型的信心數值尚未經本專案校準，不能直接當成可互換的準確率。

正式品質驗收仍需人工參考逐字稿，尤其是人名、英文詞、數字、否定詞與非人聲片段。這次不自動切換現有 Groq，也不根據舊 ASR 的吻合程度設定 confidence threshold。

## 硬體與載入

主要比較的整張 GPU 用量峰值為 **3448 MiB，約 3.37 GiB**；Breeze 階段約 3352 MiB，Whisper 階段約 3448 MiB。beam 1 補測峰值也是 3448 MiB。用量由 `nvidia-smi` 每 500 ms 取樣，是全 GPU 數值，非精確的單一 process 峰值。所有正式推論均完成，未發生 OOM；結束後模型資源已釋放。

Breeze 兩次 worker 載入為 2.64 秒與 10.73 秒，Whisper 為 24.06 秒。模型檔大小、預先量化、檔案快取及系統記憶體壓力不同，不能把單次載入數字當成穩定的模型速度差。

測試 worker 開始前的可用實體 RAM 約 0.50–1.51 GiB；測試依可用 commit memory 與單模型隔離進行，未調低 app 原有的 2 GiB 啟動保護。此次沒有量測完整 host RAM 尖峰，也未測試與正式 assistant、其他 GPU 模型同時運作，所以不能據此移除日常啟動保護。

## 可重現結果

- 主要比較：`ai_voice_assistant/asr_eval_outputs/breeze_gpu_20261117_195829/`。
- beam 1：`ai_voice_assistant/asr_eval_outputs/breeze_gpu_20261117_201303/`。
- 合併頁面及 CSV：主要比較目錄下的 `combined/`。
- `verification.json`：40 段音檔前後 hash、一致的選樣與總推論數。
- `analysis.json`：分組時間、無溫度重試的語言對照、兩輪一致性。

重現指令與模型準備方式見 [設定指南](breeze_asr25_setup.md)。報表腳本的方法測試為 8 passed，並檢查缺漏／重複執行不能被彙總為完整結果。這次沒有修改原始錄音或私人辨識設定。
