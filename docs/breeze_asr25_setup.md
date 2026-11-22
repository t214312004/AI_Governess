# Breeze-ASR-25 本地語音辨識

Breeze-ASR-25 已整合到現有 `local` 語音辨識服務，作為可選的試用模型。一般 Whisper、Groq、Gemini 設定各自保留；選擇 Breeze 不會修改雲端服務的語言或提示。模型下載不會自動切換目前使用的辨識服務。

## 使用方式

在 `start.bat` 的「聲音與裝置」選擇：

1. 語音辨識服務：`local`。
2. 本地辨識模型：`Breeze-ASR-25（試用）`。
3. 按「下載／校驗 Breeze 模型」。約下載 1.56 GB；可停止，重試時重用已通過校驗的完整檔案。
4. NVIDIA GPU 使用 `cuda / int8_float16`，先保留解碼語言 `auto`、搜尋寬度 `5`。
5. 使用「選擇音檔辨識」或「錄音 5 秒並辨識」測試，再儲存並啟動。

模型不含標點，初版不額外加辨識提示。`auto` 接近官方 Transformers 範例的語言偵測流程，但 CT2 與官方 reference 的完整品質對照仍待實測；`en / zh` 留作同一音檔的對照選項。顯示的偵測語言不等於輸出字形或要求翻譯成該語言。

GPU 的 `int8_float16` 以降低記憶體占用為起點；可另測 `float16` 執行精度，但目前下載的是 INT8 權重，改執行精度不會恢復成完整未量化 FP16 模型。使用 CPU 時請改選 `int8 / int8_float32 / float32`，實際速度需自行測量。

## 命令列準備與檢查

在專案根目錄的 PowerShell 執行：

```powershell
$env:PYTHONUTF8 = "1"
.\ai_voice_assistant\venv\Scripts\python.exe -B .\scripts\prepare_breeze_asr25.py
.\ai_voice_assistant\venv\Scripts\python.exe -B .\scripts\prepare_breeze_asr25.py --verify-only
.\ai_voice_assistant\venv\Scripts\python.exe -B .\scripts\benchmark_breeze_asr25.py --check
```

`--verify-only` 會重新計算檔案 hash；一般啟動只檢查固定 manifest 與檔案大小，避免每次啟動讀取 1.55 GB。`--check` 不載入模型；若 RAM 不足或檔案未備妥，會回傳非零 exit code 與原因。

Windows 可用 RAM 不足 2 GiB 時，會暫停 Breeze 載入並提示關閉其他程式。2 GiB 是避免在嚴重記憶體壓力下啟動的保護門檻，並非足夠記憶體的保證；建議先釋出 4–6 GiB。磁碟需要下載檔案大小之外至少 1 GiB 空間。

預設目錄是 `ai_voice_assistant/models/breeze-asr-25-ct2-int8-float16/`，不加入 Git。若改放其他位置，UI 與命令列須選同一目錄；相對路徑均以 `ai_voice_assistant/` 為基準。

## 同一音檔比較三種解碼語言

```powershell
.\ai_voice_assistant\venv\Scripts\python.exe -B .\scripts\benchmark_breeze_asr25.py --audio C:\audio\sample.wav
```

預設依序比較 `auto / en / zh`，每種執行兩次；只使用本機音檔與模型，不讀取雲端 API key，也不傳送音訊。JSON 結果列出逐字稿、實際語言、用時、平均 log probability 與 no-speech probability。首次推論包含暖機成本，不能只憑不同設定的先後執行時間宣稱性能差異。這個工具不是官方 Transformers reference，亦不會自動判定逐字稿正確率。

可使用 `--language auto`、`--compute-type float16`、`--beam-size 1` 調整對照；`--output <path>` 可另存 JSON。輸出包含逐字稿，私人音訊的測試結果請保存於私人目錄。

## 既有錄音的 GPU 批次對照

```powershell
.\ai_voice_assistant\venv\Scripts\python.exe -B .\scripts\benchmark_asr_archive_gpu.py --samples 40 --repeats 2
```

這個工具固定使用 `cuda / int8_float16`，依序載入 Breeze 與已快取的 Whisper-large-v1，缺少 CUDA 或本地模型時直接失敗，不改用 CPU，也不下載替代模型。Breeze 比較 `auto / en / zh`；Whisper-large-v1 比較原本的 `zh + 繁體提示` 與 `auto + 空提示`。

樣本從 `whisper_audio_archive/` 依短句、長句、近期錄音、歷史空白／雜訊與含英文字的片段分層挑選，兩輪使用同一份選樣 manifest，並記錄音訊 hash。舊逐字稿僅作文字差異對照，不是人工正解。此診斷樣本不代表全體使用者錄音的隨機抽樣。

為了執行受控的獨立 GPU 測試，批次 worker 不套用日常啟動的 2 GiB 實體 RAM 門檻，而是要求 Windows 至少 6 GiB 可用 commit memory，再逐一載入模型。這不會修改 app 的啟動保護；GPU 推論仍然需要系統記憶體，請避免同時跑其他大型模型。

結果寫入 Git 忽略的 `ai_voice_assistant/asr_eval_outputs/`：

- `comparison.html`：可播放原始錄音、搜尋文字並逐段對照五組輸出，只讀取本機音檔。
- `comparison.csv`、各模型 `*.jsonl`：逐段、逐輪的原始與過濾後文字、信心資訊和時間。
- `manifest.json`、`*_metadata.json`、`gpu.csv`：選樣、來源版本、載入與暖機，以及 GPU 用量紀錄。
- `summary.json`：排除載入／暖機的 p50、p95、real-time factor 與輸出吻合數；吻合數不是準確率。

逐字稿與音檔連結屬私人資料，請勿將上述結果加入 Git。比較時間包含 ASR 的特徵與解碼處理，不包含音檔讀取、VAD、LLM、TTS 與應用層提示回聲重試；預設 temperature fallback 保留，所以重試造成的長尾也會被量到。

速度選項可用 `--models breeze --breeze-languages auto --beam-size 1` 單獨測試；要和先前批次完全使用同一批錄音，加上 `--reuse-manifest <先前結果目錄的 manifest.json>`，工具會核對音檔 hash。

## 來源與離線行為

- 原始模型：[MediaTek-Research/Breeze-ASR-25](https://huggingface.co/MediaTek-Research/Breeze-ASR-25)，revision `cffe7ccb404d025296a00758d0a33468bec3a9d0`。
- 初版使用社群 [shdennlin/breeze-asr-25-ct2](https://huggingface.co/shdennlin/breeze-asr-25-ct2) 的 `int8_float16`，revision `70660216b01a6f6b7b8c5690767a4763df61755f`。它是 CT2 轉換與量化版本，並非 MediaTek 官方原始權重格式。
- `model.bin` SHA-256：`27f279d2653a6484c680d55182fa7ce8450dddfead77c6288ba90493ae1020a6`。
- 每個下載檔案均核對固定尺寸與 hash；全部完成後才產生 `breeze-model.json`。隨模型保存原始 Apache-2.0 `LICENSE` 與來源、revision、量化資訊。

Breeze 啟動一律使用完整的本機模型路徑與 `local_files_only=True`，缺檔或推論失敗不會自動下載或改送雲端。可手動切回原 Groq／Gemini 服務。本地 ASR 不代表後續 LLM／TTS 也離線。

本次整合未替換正式 venv 的 CPU-only PyTorch；CTranslate2 的 GPU 推論使用既有 cuBLAS／cuDNN，與 PyTorch CUDA build 分開。

詳細研究與未驗證限制見 [整合評估](breeze_asr25_evaluation_2026-11-17.md)。正式品質驗收仍需包含人工校對的個人語音、靜音與噪音、華英混用、數字與否定詞，以及長時間運作。

## 2026-11-17 實作驗證

- 完整測試套件：1342 passed、42 skipped；另執行 Breeze 與既有聲音設定畫面的 native Tk 測試，2 passed。
- 模型已下載至預設目錄，下載時逐檔校驗後，再用 `--verify-only` 完整驗算通過；模型與測試錄音不提交 Git。
- 本機 `--check` 正確回報模型已備妥、可用 RAM 不足 2 GiB。後續以獨立 worker 完成 [40 段實際錄音、480 次 GPU 推論](breeze_asr25_gpu_benchmark_2026-11-17.md)，三種語言與搜尋寬度的時間／文字差異已有紀錄，人工正確率仍待校對。
- 目前既有辨識服務設定未切換。Breeze 保持可選試用，釋出記憶體後可在設定畫面測試。
