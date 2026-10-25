# Pre-submit audit — 2026-10-25

本輪以 `fcd1407` 為基準，檢查所有待提交的 tracked changes、刪除項目與新增原始碼，並檢查準備公開的文件與設定。主要範圍為 Gemini STT／TTS、Antigravity 官方 ACP、共用 transport、初始設定 UI、裝置與 credentials、filesystem MCP，以及先前累積的 pipeline／logging 修補。

## 本輪新增修補

| 問題 | 修補與證據 |
| --- | --- |
| Gemini TTS 在取得 synthesis lock 後、`bounded()` 回傳前收到取消，外層尚未標記 ownership，導致鎖無法釋放，後續回覆一直等待。 | 在 acquire task 內記錄 ownership；regression test 在取得鎖的瞬間設定取消，確認釋放鎖且下一輪可正常生成。 |
| 舊 Antigravity `print_timeout` 遷移產生浮點秒數，但 startup schema 仍以 public default 的整數型別驗證，連 `5m0s` 都可能阻擋啟動。 | 秒數 duration 採浮點欄位型別，保留 counters／sample sizes 的整數限制；測試 `5m0s` 與 `250ms` 的 migration、驗證、編輯、保存與重新載入。 |
| STT 模型背景載入期間取消或關閉，等待中的 `transcribe()` 仍等待載入完成，之後可能開始已取消的工作。 | 每批工作保留獨立 cancellation event，載入等待可中止，進入 adapter 前再次檢查；Gemini 接收相同 event，完成後也丟棄失效結果。測試確認 cancel／close 會停止等待，cancel 後的新工作仍可使用。 |
| 本機 benchmark review 將 manifest 的 sample ID／hash 直接插入 HTML；音檔名稱中的 `#`／`%` 也未做 URL encoding。缺少第一輪的 TTS 結果可造成 IndexError。 | escape HTML text／attributes、encode audio URLs，支援跨 Windows volume 的 file URI，略過不存在的第一輪；以含 markup／保留字元的 synthetic manifest 及不完整 TTS 紀錄測試。 |
| 兩個 benchmark CLI 解析 Google key 時忽略 `gemini.api_key_env`。 | 與正式 runtime 一致，將自訂環境變數名稱傳入 key resolver。 |

上述 lock、migration、background cancellation 共 5 個新增測試案例，在修補前均重現失敗；修補後通過。另增加 HTML review regression，合計新增 6 個案例。順手移除新增模組與修改檔案中 4 個未使用的 imports，沒有進行其他 refactor。

## Dependency 安全檢查

使用隔離安裝的 `pip-audit` 查詢 public `requirements.txt` 的直接 pin，核對官方 package metadata／advisories 後更新：

| Dependency | 原版 | 本輪 pin |
| --- | --- | --- |
| aiohttp | 3.13.3 | 3.14.5 |
| Pillow | 12.1.1 | 13.0.0 |
| torch | 2.10.0 | 2.13.0 |
| torchaudio | 2.10.0 | 2.11.0 |

TorchAudio 2.11 使用 stable ABI，官方支援 PyTorch 2.11 及其後版本，詳見 [官方 compatibility 說明](https://docs.pytorch.org/audio/stable/installation.html)。Gemini payload／PCM 格式對照 [Google speech generation 文件](https://ai.google.dev/gemini-api/docs/speech-generation)；Antigravity 1.4.3 的 Windows archive hash 對照 [官方 ACP Registry](https://github.com/agentclientprotocol/registry/blob/main/antigravity-acp/agent.json)。

**保留的 compatibility 例外：`setuptools==80.9.0`。** `resemblyzer==0.1.4` 所依賴的 `webrtcvad` 仍 import `pkg_resources`，直接升級至移除此 API 的 setuptools 會破壞聲紋 backend。掃描仍回報以下兩項 unique advisories，沒有將它們標成已修復或忽略掃描結果：

- [PYSEC-2026-3447 / CVE-2026-59890](https://github.com/pypa/setuptools/security/advisories/GHSA-h35f-9h28-mq5c)：macOS source distribution 的 Unicode exclusion bypass；本專案為 Windows app，沒有 source distribution build 流程。
- [GHSA-xmj3-9gf7-h52w](https://github.com/pypa/setuptools/security/advisories/GHSA-xmj3-9gf7-h52w)：legacy wheel installer 的 Windows path escape；app runtime 沒有使用該 installer。仍不可將此 pin 當成適合處理不可信安裝包的 build environment。

後續須處理 upstream `webrtcvad`／聲紋 dependency 的 `pkg_resources` 相容性，再移除這個 pin；不以靜默退回 MFCC 的方式掩蓋功能退化。本輪直接 pin 掃描只剩上述 setuptools 公告，PyPI feed 對其中一項有重複紀錄。此檢查不是完整 transitive lockfile audit。

新版本安裝到 OS temporary directory 作為測試 overlay，包含 aiohttp 所需的 `yarl==1.25.1`；**既有 `venv` 沒有升級或修改套件**。overlay 的 import versions 與 `pip check` 均已確認。正常安裝 `requirements.txt` 時，pip 會解析 aiohttp 的新版 yarl requirement。

## 驗證與公開資料檢查

- 所有 Git 候選文字檔 strict UTF-8 解碼成功，沒有 replacement characters；158 個 Python 檔案 AST parsing 與 6 個 JSON 檔案 parsing 通過。沒有改寫私人 workspace Markdown。
- 原始碼檢查涵蓋變更的 adapters、timeout／retry／cancel／close、process ownership、session restore、設定保存／rollback、音訊重採樣、filesystem root／symlink／Windows ADS 驗證與原子寫入。既有及新增相關測試均保留。
- `pyflakes` 沒有發現 undefined names；仍有既有未使用 imports、re-exports 與 local variables，沒有為了消除 warning 進行無關修改。
- 檢查候選檔案的常見 credential／private-key patterns、email 與 Windows user paths。命中的 email／user paths 均為 `test@example.com`、`C:/Users/test` 等 synthetic fixtures；沒有發現實際 key 或 private config 被納入。
- 一般完整測試於新版 dependency overlay 執行：**1229 passed、31 skipped、3 warnings**。31 個 skipped 為 opt-in 原生 UI 測試；warnings 來自 TorchScript、resemblyzer 的 SciPy import 與 webrtcvad 的 `pkg_resources` 相容性。
- 設定 `AI_GOVERNESS_NATIVE_TESTS=1` 後，最終完整重跑：**1251 passed、9 skipped、3 warnings**。新增／修改的啟動設定、Google key、audio controls、模型查詢、取消、保存與 scaling 等原生 UI 測試通過；9 個 session 測試因 input desktop 前提不成立而 skipped，沒有新增 skip 來掩蓋一般程式測試失敗。
- 提交前執行 `git diff --check`、staged content／private-path 檢查與 `scripts/pre_git_audit.ps1`，確認 `[OK]` 後才 commit。

原生測試曾在不符合 desktop 前提的環境執行：Edge 有 owned window，但其 render HWND 受到遮蔽而未完成嵌入；HTML 額度也正確保持暫停。進一步確認 `desktop_available()` 為 false，因此為 session fixture 增加其原先就聲明需要的「unlocked interactive input desktop」檢查；不在產品中加入測試用 browser flags，也不將無效環境下的執行算成 Edge 驗收通過。另一次 Tcl initialization error 在單獨重跑同一 startup test 時通過，最終結果以完整重跑為準。

本輪未進行真實付費 STT／TTS／LLM 請求、OAuth 重新登入、實體麥克風／喇叭／攝影機端到端驗收，亦未改動目前帳號的 runtime 安裝或 GitHub repository visibility。歷史 benchmark／ACP probe 文件的數字為其標示日期的既有結果，不代表本輪重新測得。

測試命令為 `python -m pytest -q -ra -p no:cacheprovider`，working directory 為 `ai_voice_assistant/`；啟用原生 UI 時額外設定上述環境變數。測試過程使用 `PYTHONDONTWRITEBYTECODE=1` 與 temporary dependency overlay；正常環境應先依 `requirements.txt` 安裝相同版本再重跑。
