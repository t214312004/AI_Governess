# Breeze-ASR-25 整合與本機環境評估

研究日期：2026-11-17。專案基準 commit：`5f162e912d181ec69d4299e438efb1fd47936be4`。

本文保留實作前的研究快照；後續已加入可選的 Breeze profile 與校驗下載工具，使用方式和驗證狀態見 [設定指南](breeze_asr25_setup.md)。

**建議將 Breeze-ASR-25 納入正式整合的候選，以既有 `faster-whisper / CTranslate2` 執行，先作為可選的本地辨識設定。現階段尚不足以直接取代目前的 Groq。** 模型的目標語境符合本專案，GPU 與現有 CUDA 推論路徑也已通過輕量實測；剩下的主要決策依據是 Breeze 本體的解碼相容性、個人語音準確率與暖機後延遲。

本次完成官方文件、論文、設定檔、部分權重與專案程式碼查核，以及本機 CUDA smoke test。未安裝套件、未下載完整 Breeze 權重、未切換服務或修改本機設定，亦未將私人錄音送往外部服務。本文區分上游研究結果、本機已測結果與待驗證的工程推估。

## 1. 模型本質與適用範圍

Breeze-ASR-25 是 MediaTek Research 對 Whisper-large-v2 的微調，論文名稱為 Twister，主攻台灣華語與華英混用。它屬於 encoder-decoder ASR，適合將一段音訊轉成文字；不能因為現有程式持續收音，就將它視為原生 streaming ASR。[官方模型卡](https://huggingface.co/MediaTek-Research/Breeze-ASR-25)、[研究論文](https://arxiv.org/html/2506.11130v2)

本次從官方 `model.safetensors` 的 header 直接核對到：

| 項目 | 查核結果 |
|---|---|
| 模型架構 | `WhisperForConditionalGeneration`；encoder / decoder 各 32 layers |
| 儲存的參數總數 | 1,543,304,960，約 1.54B；Hub 顯示的 2B 是較粗的標示 |
| mel bins / 取樣率 | 80 / 16,000 Hz |
| 特徵擷取視窗 | 30 秒；較長音訊由推論流程逐段處理 |
| 權重格式 | Safetensors，實際 tensor dtype 為 BF16 |
| 單一 Safetensors 檔案 | 3,086,761,032 bytes，約 3.09 GB / 2.87 GiB |
| 官方權重 revision | `cffe7ccb404d025296a00758d0a33468bec3a9d0` |
| 權重 SHA-256（Hub 公布） | `c5d952b3bc03ea277209aff0ef5b5c4c055d74449ff794c02d8f4e315fdef6b6` |

尺寸、revision 與 hash 來自 [Hub API](https://huggingface.co/api/models/MediaTek-Research/Breeze-ASR-25?blobs=true)；架構與音訊規格見 [config.json](https://huggingface.co/MediaTek-Research/Breeze-ASR-25/blob/cffe7ccb404d025296a00758d0a33468bec3a9d0/config.json) 及 [preprocessor_config.json](https://huggingface.co/MediaTek-Research/Breeze-ASR-25/blob/cffe7ccb404d025296a00758d0a33468bec3a9d0/preprocessor_config.json)。未下載完整檔案，因此尚未自行驗算完整權重 hash。

「台灣華語」指 Taiwanese Mandarin，不能直接延伸成已驗證台語、客語、粵語、日語或所有 Whisper 語言都有相同表現。保留 tokenizer 的語言代碼，也不等於那些語言都是本模型的主要訓練與驗證目標。

## 2. 繁體中文能力的證據與限制

以下是上游公布的評測數值，越低越好，並非本機測量：

| 資料集 | Whisper-large-v2 Auto | Whisper-large-v3 Auto | Breeze-ASR-25 |
|---|---:|---:|---:|
| CommonVoice16-zh-TW | 9.84 | 8.95 | **7.97** |
| ASCEND-MIX | 21.01 | 25.13 | **16.38** |
| CSZS-zh-en | 29.49 | 26.43 | **13.01** |
| ML-lecture-2021-long | 6.13 | 6.41 | **4.98** |
| Formosa-Course | **9.50** | 9.67 | 9.94 |
| FormosaSpeech | 22.34 | **21.22** | 22.09 |

來源：[官方評測表](https://huggingface.co/MediaTek-Research/Breeze-ASR-25#performance)。模型卡稱其為 word error rates；論文正式採 MER，華語部分按字、英語部分按詞計算。不能將這些數值轉成「整句正確率」或跨資料集直接相加平均。[評測方法](https://arxiv.org/html/2506.11130v2#S4.SS5)

CommonVoice 的 9.84 → 7.97 是約 19% 的相對錯誤率下降，並非準確率增加 19 個百分點。CSZS 的改善很大，但該資料集是合成的中英混用語音；也有 Formosa 類別的改善很小或退步。上游結果支持它是很好的候選，尚不能證明它會勝過本程式目前實際呼叫的 Groq 服務。

訓練方法以合成華語配合真實英語與混用資料進行適配。論文的原始收集量與篩選、擴增後訓練量不同；不能把模型卡三列原始資料直接相加，當成最終獨立真實語音時數。這種方法有助於補足文字與詞彙，但使用者的麥克風、環境噪音、說話習慣與短指令仍需要實測。[論文方法與資料](https://arxiv.org/html/2506.11130v2)

另有 2026 年技術講課研究，在其 16.92 小時測試集上，Breeze-ASR-25 的 CER 為 10.72，Whisper-large-v3-turbo 為 11.95；但 Breeze 的技術詞 recall 在另一個 5.01 小時子集仍只有 52.50%。這補強了候選價值，也說明整體 CER 好看仍可能聽錯關鍵名稱。該研究有原模型論文的共同作者，且不是本專案的使用者錄音測試。[技術詞辨識研究](https://arxiv.org/html/2607.05058v1#S4)

## 3. 解碼語言：最需要先解決的整合問題

使用者提到「不要修改預設解碼語系」的方向有機制上的理由：論文使用由華語、英語 language-token embeddings 平均初始化的 shared embedding，支援混用解碼。但本次未找到官方針對所有 runtime、所有轉換版本都適用的統一設定保證。不能只憑這句話推導出固定使用 `zh`、`en` 或 `auto`。

目前官方檔案的實際內容如下：

| 位置 | 與語言有關的行為 |
|---|---|
| 官方 `config.json` | `forced_decoder_ids` 的首個 language token 是 50259，即 `<\|en\|>` |
| 官方 `generation_config.json` | 第一個 language token 是 `null`，後面指定 `transcribe` |
| 官方 Transformers `run.py` | 沒有另傳 `language`；保留所載入 generation 設定 |
| 本專案 `Transcriber` | 預設且目前本機設定均為 `language="zh"`；每次辨識明確傳入 |
| 本專案設定 `auto` | 轉成 Python `None`，進入 faster-whisper 的語言偵測流程 |

來源：[官方 config](https://huggingface.co/MediaTek-Research/Breeze-ASR-25/blob/cffe7ccb404d025296a00758d0a33468bec3a9d0/config.json)、[官方 generation config](https://huggingface.co/MediaTek-Research/Breeze-ASR-25/blob/cffe7ccb404d025296a00758d0a33468bec3a9d0/generation_config.json)、[官方範例](https://github.com/mtkresearch/Breeze-ASR-25/blob/main/run.py)。

查閱 `transformers==4.48.3` 的實作可確認：上述 generation 設定的 `null` 會觸發 language detection；它不是無條件採用 `config.json` 的 50259。此版本是官方設定檔記錄的版本，本機並未安裝；日後採其他版本須重新核對。[該版本 generation 實作](https://github.com/huggingface/transformers/blob/v4.48.3/src/transformers/models/whisper/generation_whisper.py#L1369)

另外，已安裝的 CTranslate2 4.7.1 Whisper converter 會保留 suppression、alignment heads、language IDs 等資訊，**沒有將 Hugging Face 的 `forced_decoder_ids` 直接轉成固定解碼前綴**。faster-whisper 1.2.1 則自行依 `language` 建立 tokenizer 前綴。因此把 `generation_config.json` 一併複製進 CT2 資料夾，不能據此宣稱解碼語義就完全相同。[CTranslate2 converter](https://github.com/OpenNMT/CTranslate2/blob/v4.7.1/python/ctranslate2/converters/transformers.py)、[faster-whisper 1.2.1 實作](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py#L921)

本次還以 HTTP Range 僅讀取官方權重 header 與兩個 token rows，確認 `<|en|>`、`<|zh|>` 的 embeddings 並不相同。這證明切換 language token 並非無效操作；但無法僅靠兩列權重判定哪個解碼設定在實際語音上最佳。

建議的正式處理方式：

1. 固定官方 revision，建立不額外覆寫語言的 Transformers reference。
2. 用相同音訊比較 CT2 的 `language=None / "en" / "zh"`，記錄前綴、偵測語言及逐字稿。
3. 選出能保留 reference 行為且通過華英混用評測的設定，再寫入 Breeze 專屬 profile。
4. 若採 `None`，必須確認它實際選到的 token；若採 `en`，必須驗證它仍逐字轉錄華語與英語，不能當成「只辨識英文」或要求翻譯。

這裡的 `en` 是需要對照的候選，尚未被本次研究認定為正式正確答案。也不能把其他人轉換模型 README 中的 `language="zh"` 當作上游混用解碼的正確性證明。

## 4. 明確的產品限制

**模型不支援標點。** 作者在 2025-07-25 的回覆表示，早期標點造成不穩定，因此將標點換成空格；增加 `initial_prompt` 並不能視為支援標點的解法。[作者回覆](https://huggingface.co/MediaTek-Research/Breeze-ASR-25/discussions/2#688349b81cfe0bcc34531eeb)

對本專案的影響：

- 短指令與提供給 LLM 的語句仍可使用；顯示用逐字稿若需要標點，可另加後處理。
- 保存原始 ASR 文字，再另存顯示文字，方便追查；後處理要避免改動否定詞、數字、名稱或程式碼。
- 初始驗證先採 `initial_prompt=""`，降低既有繁體逐字稿提示對模型行為的干擾；詞彙提示是否有益再另行比較。
- 保留目前 Silero VAD、雜訊文字過濾與提示回聲處理。模型卡的高準確率不能證明靜音、音樂或 TTS 回授一定不會產生文字。

Hub 的「靜音片段」討論已被發問者編輯成 `fixed`，未保留足夠重現資訊，不能把它當成已確認仍存在的模型缺陷或完整修復證明。[討論現況](https://huggingface.co/MediaTek-Research/Breeze-ASR-25/discussions/4)

## 5. 本機環境：硬體可行，當下系統資源偏緊

以下是查核當時的快照，RAM、磁碟與 GPU 用量會變動：

| 項目 | 實際狀態 | 評估 |
|---|---|---|
| OS | Windows 11 Home，64-bit，10.0.26300 | 現有 CT2 Windows wheel 可執行 |
| CPU | AMD Ryzen 7 260，8 cores / 16 threads | 可作 CPU 備援；大型模型的互動延遲未測 |
| NVIDIA GPU | RTX 5060 Laptop GPU，8151 MiB VRAM | GPU 是優先路徑 |
| Driver / capability | 621.14 / compute capability 12.0 | 現有環境已完成 CUDA 推論 |
| 系統 RAM | OS 可見 15.26 GiB；可用約 0.42–0.52 GiB | 當下主要風險，不能只看 VRAM |
| C: 可用空間 | 約 13.6 GiB | 可容納單份量化模型，但完整下載、轉換與快取餘裕不足 |
| Python | 專案 venv 為 3.14.4 | 目前已安裝 CT2 路徑可用 |
| faster-whisper / CTranslate2 | 1.2.1 / 4.7.1 | 可沿用 |
| CUDA runtime 套件 | cuBLAS 12.9.1.4；cuDNN 9.20.0.48 | 完整 DLL 路徑下 cuDNN 回報 92000 |
| PyTorch | `2.13.0+cpu`，`cuda=None` | CPU-only PyTorch，不適合直接照抄官方 `.to("cuda")` 範例 |
| Transformers / accelerate / safetensors | 未安裝 | 官方 Transformers 路徑尚未備妥 |
| TorchAudio | 2.11.0 | 本次未執行其音檔讀取與完整 Transformers pipeline |

`torch` 是 CPU-only **不妨礙 CTranslate2 使用 NVIDIA GPU**，因為 CT2 是另一套推論引擎。不要為了導入 CT2 版本 Breeze，就直接替換目前正式 venv 的 PyTorch。

### 已完成的 CUDA smoke test

以已快取的 `Systran/faster-whisper-base` 執行，設定 `local_files_only=True`，不下載模型。輸入為 1 秒的 16 kHz float32 零音訊；明確使用 `beam_size=1`、`temperature=0`、`max_new_tokens=4`、不開 VAD，並完整消耗 `segments` generator，確保執行 encoder / decoder 而非只載入模型。此設定刻意允許解碼靜音，以測試計算路徑，不能拿輸出的 segment 當作正式靜音誤辨識結果。

| 執行順序 | compute_type | 載入秒數 | 載入與推論合計秒數 | 結果 |
|---|---|---:|---:|---|
| 1 | `float16` | 3.626 | 44.683 | PASS；實際 compute type 相符 |
| 2 | `int8_float16` | 0.663 | 1.438 | PASS；實際 compute type 相符 |

這兩筆不是性能比較：模型尺寸、輸入與解碼限制不代表正式工作負載，第二筆也已受第一筆暖機影響。首次耗時可能包含初始化、kernel 準備或系統記憶體壓力，本次未分析其占比。**它們只證明當前 CUDA / DLL / CT2 組合能完成兩種精度的推論，不能推算 Breeze 的速度或準確率。**

另外，`get_cuda_device_count()` 回報 1，CUDA 支援集合包含 `float16`、`bfloat16`、`int8_float16`、`int8_bfloat16` 等；CPU 支援 `float32`、`int8`、`int8_float32`。

一次僅加入 cuDNN 目錄的直接 DLL 查詢曾無法解析內部 symbol；將所有 `nvidia/*/bin` 同時加入搜尋路徑後查詢成功。此結果與專案現有多目錄 PATH 處理及已通過的推論測試一致，也說明 Windows 測試需使用完整 DLL 搜尋環境。

### 資源預估與建議

faster-whisper 上游在 RTX 3070 Ti 8 GB 對 large-v2、beam 5 的參考測量約為 FP16 4525 MB、INT8 2926 MB。**這是同架構的別台機器參考值，並非 Breeze 在此筆電的實測。** 8 GB VRAM 有合理機會容納單路推論，但仍要測長句、尖峰用量及與其他 GPU 工作同時執行的情況。[上游 benchmark 與 GPU dependencies](https://github.com/SYSTRAN/faster-whisper#benchmark)

建議從 `device="cuda", compute_type="int8_float16"` 開始，另保留 FP16 品質對照；量化是否影響少見名稱與英文字，需實測才能定案。`compute_type` 是執行精度，與磁碟模型格式、是否在轉換時量化是兩個可分開控制的選項。[CTranslate2 quantization](https://opennmt.net/CTranslate2/quantization.html)

開始 Breeze 大型模型實測前，建議先讓可用 RAM 回到至少約 4–6 GiB，並視轉換方式預留約 15–20 GiB 磁碟空間。這些是本專案的操作餘裕建議，不是上游公布的最低需求。當下約 0.5 GiB 可用 RAM 不適合直接再載入大型模型或作轉換。若長期同時執行多個大型程式，32 GB RAM 會較有餘裕，但仍需先確認筆電的記憶體擴充能力。

## 6. 可選整合路徑

| 路徑 | 相容成本 | 本專案建議 |
|---|---|---|
| 官方 HF → 自行轉 CT2 → faster-whisper | 沿用現有 runtime；須驗證前綴、tokenizer 與量化 | **正式整合優先**；可固定來源、版本與 hash |
| 社群 CT2 成品 → faster-whisper | 最快試跑；來源、轉換流程與品質須核對 | 可作驗證捷徑，不能直接視為已通過正式驗收 |
| 官方 Transformers pipeline | 適合作 reference；需另一組 dependencies 與 CUDA PyTorch | 用獨立環境建立對照，避免改動正式 venv |
| 官方 patched whisper CLI | 需用官方指向的 fork；不是目前 faster-whisper 套件 | 可作另一條參考，無需作為主要整合方向 |
| 官方 ONNX → sherpa-onnx | 專案已有 sherpa-onnx，但目前用於 wake word，需另加 ASR adapter | 可研究 CPU 部署；不是現有 CT2 路徑的直接替換 |
| whisper.cpp / GGML、GGUF | 需新增執行環境與封裝 | 本機已有可用 NVIDIA CT2，暫無優先採用理由 |

CT2 官方支援 Whisper 轉換；faster-whisper 接受 CT2 模型目錄或 Hub repo，但**不能將原始 Safetensors repo 當成 CT2 模型直接載入**。[官方轉換文件](https://opennmt.net/CTranslate2/guides/transformers.html#whisper)

社群成品查核範例：[shdennlin/breeze-asr-25-ct2](https://huggingface.co/shdennlin/breeze-asr-25-ct2) 的 revision `70660216b01a6f6b7b8c5690767a4763df61755f`：

- `float16/model.bin`：3,086,913,037 bytes。
- `int8_float16/model.bin`：1,551,140,573 bytes。
- `int8/model.bin`：1,558,764,253 bytes。

該 repo 將不同精度放在子目錄。若試用，應只下載所選子目錄，將那個目錄交給 `WhisperModel`；目前專案 wrapper 未提供 `subfolder` 選項。以上僅核對檔案存在與大小，未驗算模型內容或其量化品質。[檔案 metadata](https://huggingface.co/api/models/shdennlin/breeze-asr-25-ct2?blobs=true)

官方也有 [ONNX 版本](https://huggingface.co/MediaTek-Research/Breeze-ASR-25-onnx-250806)，但模型卡只有簡短轉換說明；不能由 repo 存在就推定 Python ASR、CUDA provider、前綴及延遲已適配本專案。原版 FP32 encoder / decoder 外部權重合計約 6.17 GB；INT8 ONNX 兩檔合計約 1.77 GB，應挑需要的檔案下載。[ONNX 檔案 metadata](https://huggingface.co/api/models/MediaTek-Research/Breeze-ASR-25-onnx-250806?blobs=true)

正式轉換時只取模型、tokenizer、processor、generation 設定與授權檔。上游 repo 還有訓練狀態與不同 checkpoint，整包約 16 GB；在目前磁碟空間下，不適合不加篩選地下載整個 snapshot。

## 7. 專案需要調整的具體位置

| 位置 | 現況 | 正式整合所需處理 |
|---|---|---|
| `core/transcriber.py:209` | `Transcriber` 已可傳自訂模型路徑 | 沿用；加 Breeze profile，避免以檔名猜測設定 |
| `core/transcriber.py:219–244` | 共用 language / prompt，預設強制 `zh` | 改為 profile 專屬且經驗證的解碼設定 |
| `core/transcriber.py:246–275` | 只回文字；失敗記錄後回空字串 | 保留 logprob、no-speech、用時與錯誤原因供診斷 |
| `core/transcriber.py:605` | 背景載入、180 秒等待、支援 local / Groq / Gemini | 沿用；下載與載入分開，正式啟動使用已完整準備的模型 |
| `core/transcriber.py:759` | 非 16 kHz 音訊會 resample | 與 Breeze 16 kHz 相容 |
| `core/assistant.py:200` | 啟動時傳遞共用設定 | 將 local profile 與 Groq 設定分開，避免互相改寫 |
| `ui/audio_settings.py:97`、`core/settings_schema.py:144` | 本地模型欄可輸入 repo / 路徑 | 增加明確 Breeze 選項與模型準備狀態 |
| `ui/audio_preview.py:151` | 試聽辨識也直接使用共用設定 | 必須套用相同 profile，避免試聽與正式辨識不一致 |
| `ui/main_window.py:3391` | 切到 cuda 時會將 compute type 改為 FP16 | 避免覆蓋已選的 `int8_float16` |
| `core/vad.py`、`core/assistant.py:3527` | 先收音與斷句，再整段 STT | 可直接沿用；不能宣稱因此具備原生 streaming |

相對目錄以上均為 `ai_voice_assistant/`。查核版本如文件開頭所列。

目前本機辨識服務為 Groq，本地模型欄仍為 `large-v1 / cpu / int8 / zh`。這不是 Breeze 設定；僅切換 backend 不會自動得到 Breeze 或 CUDA 加速。

初版建議保留 `backend="local"`，增加可選的 Breeze model profile，由同一處解析模型路徑、精度、解碼語言、prompt 與 beam 設定，供正式服務與預覽共用。模型下載、校驗在啟動前完成；正式啟動固定本機路徑與 revision，斷網也能載入。模型權重持續放在 gitignored 的 `models/`，不提交 Git。

現有本地 adapter 的錯誤回傳可能與「沒有聽到文字」混淆，正式版本應明確顯示模型未備妥、CUDA / 記憶體錯誤與純靜音的差異。若需要真正中止進行中的 CT2 native 推論，單靠目前的 cancel event 只會丟棄結果；可另評估 worker process 隔離。這不必成為初次驗證的前置改造。

目前 `min_silence_duration_ms=1500`，另有 endpoint grace / fallback 規則。使用者感受到的停頓包含斷句等待、STT、LLM 與 TTS；評估 Breeze 時須獨立記錄 STT 用時，不能把整段等待全歸因於模型。

## 8. 授權、維護與公開發布

模型權重的官方授權為 Apache-2.0；範例 GitHub repo 為 MIT。正式發行若包含模型或轉換產物，需保留相應授權與 attribution，並記錄轉換、量化等修改；不能因範例程式是 MIT，就把權重全部標成 MIT。[權重 LICENSE](https://huggingface.co/MediaTek-Research/Breeze-ASR-25/blob/main/LICENSE)、[範例程式 LICENSE](https://github.com/mtkresearch/Breeze-ASR-25/blob/main/LICENSE)

ONNX repo 的 metadata 標成 MIT，與原始權重的 Apache-2.0 不同，選用時應核對其完整授權鏈；目前推薦的 CT2 路徑可直接保留原權重 Apache-2.0 與轉換工具的授權資訊。

截至本次查核，ASR-25 官方權重最後更新為 2025-07-08，範例 repo 的 pushed time 為 2025-07-01。這不代表無法使用，但上游研究模型不會替本專案承擔持續相容性驗證，應自行固定環境與 regression set。

2026 年已有 **Breeze-ASR-26**，但其官方模型卡描述的是台語辨識、輸出華語漢字的 BreezeASR-Taigi，不能因為版本號較大，就當成 ASR-25 的台灣華語辨識直接升級。[ASR-26 模型卡](https://huggingface.co/MediaTek-Research/Breeze-ASR-26#model-description)

本地 ASR 可讓音訊辨識在本機進行，但若後續文字仍送往雲端 LLM / TTS，整個 assistant 就仍不是完全離線。錄音保存功能也需要照既有使用者設定處理。

## 9. 正式啟用前的驗收

先做小規模 feasibility，再做整批評測；以下是建議的專案驗收標準，並非廠商保證：

1. **環境與載入**：釋出 RAM 後，載入 Breeze CT2，確認冷啟動、暖啟動、離線載入、缺檔與錯誤顯示；量測 RAM / VRAM 尖峰。
2. **解碼一致性**：固定官方 reference 與來源 revision，完成 `None / en / zh` 對照；特別檢查華英句內切換、整句英文、專有名詞與短句。
3. **個人使用集**：蒐集約 100–200 句、20–30 分鐘的人工校對音訊，涵蓋近講、遠講、風扇、停頓、否定、數字、日期、喚醒後短指令、英文名稱與 30–60 秒長段。模型、精度與服務比較使用完全相同的音訊，不能各錄一版。
4. **品質**：同時計算華語 CER、英語 WER / mixed MER、關鍵詞與指令意圖正確率；另檢查原始繁體字輸出。若先將簡體轉繁體才計分，須另列原始字形表現，避免掩蓋產品問題。
5. **互動速度**：建議暖機後 1–10 秒短句的純 STT 以 p50 ≤ 1 秒、p95 ≤ 2 秒為初始目標，長段另看 real-time factor。達不到時再比較 beam 1 / 5，依實測調整目標與設定。
6. **可靠性**：靜音、音樂、環境聲、播放中的 TTS、重複句與提示回聲都要測；測試集內不得造成錯誤工具執行。通過有限測試不等於零風險。
7. **長時間運作**：至少一輪 30–60 分鐘真實流程，確認持續效能、記憶體、取消與關閉、背景載入，以及其他 GPU 工作共存。
8. **切換與退回**：Breeze 作為可選本地方案；保留原 Groq / Gemini 設定與手動切回能力，驗證切換不覆蓋彼此的語言與 prompt。不要因本地失敗就默默將原本要求留在本機的音訊上傳雲端。

CPU `int8` 可列作備援測試，但在本機未測 Breeze CPU 延遲前，不應列為預設即時語音方案。INT8 與 FP16 的品質差異也應由相同測試集決定。

## 10. 決策記錄

| 問題 | 本次判斷 | 證據強度 |
|---|---|---|
| 是否已有本地辨識能力？ | 有，`local → faster-whisper → CT2` | 已讀取專案程式 |
| Breeze 是否相容 Whisper 架構？ | 是；原始權重需轉成既有 runtime 所需格式 | 官方架構與 converter 已查核 |
| 繁體中文與混用能力是否值得採用？ | 值得列入正式候選；不能宣稱全面勝過目前 Groq | 上游評測與另一篇研究支持 |
| 能否沿用現有 `zh` 解碼設定？ | 不應直接沿用；需 reference 與前綴回歸 | 已確認設定差異與 embeddings 不同 |
| 這台筆電 GPU 適合嗎？ | 有合理可行性，建議 CT2 `int8_float16` 起步 | 規格加既有小模型 CUDA 推論通過 |
| 當下環境適合直接載入 Breeze 嗎？ | 先釋出 RAM 與預留磁碟空間 | 約 0.5 GiB RAM 可用的快照 |
| 官方 Transformers 範例能直接跑嗎？ | 現有正式 venv 不行；缺套件且 PyTorch 為 CPU-only | 套件與 build metadata 已查核 |
| 是否已完成 Breeze 本體實測？ | 尚未，未下載或載入完整權重 | 明確保留驗證缺口 |
| 是否可現在宣布正式取代 Groq？ | 尚不可；完成解碼、品質與延遲驗收後再決定 | 缺本機與個人音訊對照 |

後續第一步是釋出足夠系統資源後，以固定來源的 CT2 Breeze 進行小規模本機測試；通過再加入正式 profile 與 UI。此研究階段沒有改動正式辨識行為。
