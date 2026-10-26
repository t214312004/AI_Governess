# Gemini API CLI 初始 UI 支援

日期：2026-10-26。追加需求：初始 UI 能安裝／更新 `gemini-api`、查詢模型，並指定所有音樂使用 `lyria-3.5`。

## 實際行為

「AI 服務」頁下方新增「Gemini API CLI 與音樂」區塊，提供音樂模型、CLI 路徑、共用 Google key、安裝／更新、唯讀模型查詢與取消操作。模型清單將 Lyria 排在前面，`music.model` 固定可選 `lyria-3.5`；查到 Clip 或其他模型不會切換選擇。所有音樂風格、純音樂及歌曲共用此設定。

CLI 路徑和音樂模型隨「儲存設定」或正常啟動保存到 layered private config；確認頁也列出音樂模型。key 沿用既有立即保存／刪除機制，不會在欄位預填、指令參數或查詢結果中顯示原值。模型查詢只執行 `--version` 與 `models list`，不會進行付費音樂生成。

安裝／更新是明確按鈕觸發的獨立立即操作。查詢 Google 官方 GitHub latest release，檢查 asset URL／architecture／SHA-256 digest，下載到 staging、核對 archive，再啟用 Windows executable。只讀取 archive 中名為 `gemini-api.exe` 的 entry，不執行外部安裝 script。版本放在目前 Windows 使用者的 `%LOCALAPPDATA%/AI_Governess/runtimes/gemini-api/`，透過 atomic `active.json` 切換，保留舊版檔案，不修改 PATH、不自動降版。

更新不需要 key；查詢使用與 Gemini 語音相同的 key，僅注入 owned child process 的 environment。沿用 `CliCatalog._run` 的輸出上限、取消、deadline 和 Windows Job process tree 清理，新增可選 `env` 參數，不改原有對話 CLI 的命令。切頁、關閉、變更 key 或 CLI 路徑會取消舊查詢、忽略過時結果；查詢列表不完整／格式錯誤／分頁重複則不使用該結果。

此工具保持獨立，不加入對話 LLM backend 清單。Gemini TTS 繼續使用現有直接 API 的串流；音樂生成、永久曲庫與白板播放器仍依[規劃書](gemini_api_cli_music_plan_2026-10-26.md)接續實作。

## 主要修改

- `utils/gemini_api_cli.py`：管理安裝、驗證與模型分頁查詢。
- `ui/gemini_api_settings.py`：初始 UI 的獨立設定與背景操作。
- `ui/startup.py`：草稿收集、確認頁、關閉／取消生命週期。
- `config.default.json`、`config.example.json`、settings schema／labels：`gemini_api_cli.executable`、`music.model`。
- `tests/test_gemini_api_cli.py`：安裝完整性、錯誤／取消與回復、憑證隔離、模型清單、設定保存及原生 UI 回歸。

## 驗證

- 用現有 key 實際透過 CLI 查到 60 個模型，含 `lyria-3.5`；沒有進行新音樂生成。
- 以正式 installer 實際下載、驗證及安裝官方 `v0.4.4`，另以 native StartupView 點擊查詢，正確顯示版本、60 個模型和 `lyria-3.5`，按鈕操作完成後恢復可用。
- 原生視窗目視檢查：音樂模型、CLI 路徑、key、更新／查詢控制項和可捲動結果皆正常；專用驗證視窗已關閉，未改使用者私人設定。
- 最終全套一般測試：`1242 passed, 34 skipped, 3 warnings`（31.06 秒）；warnings 為既有的 torch／SciPy／pkg_resources 相容性訊息。
- 包含新增功能、startup usability、Google credentials 和 audio startup 的原生測試：合併執行為 `88 passed, 1 error`。唯一 error 在建立 `CTk()` 時暫時無法讀取 `C:/Python314/tcl/tcl8.6/init.tcl`，尚未進入該項 UI 測試；相同失敗案例另開 process 重跑為 `1 passed`（5.07 秒）。新增的三項原生 UI 測試均通過。
- strict UTF-8、JSON 與交付檔案金鑰檢查通過；`git diff --check` 通過，private-path audit 回報 `[OK]`。沒有提交或推送 commit。

測試以 `PYTHONDONTWRITEBYTECODE=1`、`AI_GOVERNESS_DISABLE_LOGGING=1`、pytest `-p no:cacheprovider` 執行；原生 UI 另外設定 `AI_GOVERNESS_NATIVE_TESTS=1`。金鑰及下載的 executable 不納入 Git。
