# 初始 UI 改善與驗證（2026-10-20）

本次依 [初始 UI audit](startup_ui_audit_2026-10-20.md) 的 A01–A11 實作。操作方式見 [初始設定指南](startup_setup_guide.md)。既有 working tree 的其他修改保留；本次未提交 commit，也未更改使用者的 private config、聲紋樣本、記憶或喚醒詞檔案。

## 實作對照

| Audit | 完成的修改 |
| --- | --- |
| A01 BlueMagpie 選用未啟用 | 選用後草稿自動啟用；顯示 worker／參考音檔缺項。試聽先檢查必要設定，未備妥不開啟音訊裝置。保留 engine 未播放的原因。 |
| A02 設定驗證 | 新增穩定 schema，處理已知 enum、nullable、單位、數值與跨欄位限制。取樣率僅支援 8000／16000 Hz，對應 256／512 samples；Local／Groq 的 8 kHz 音訊先轉為 16 kHz。`auto` 語言改用提供者的自動偵測。 |
| A03 隱藏區域留白 | 移除會保留高度的空 slot，依選用服務直接顯示／隱藏整區，並保持排列順序；Google key 移到測試之前。 |
| A04 導覽被錯誤擠壓 | footer 的訊息與操作列分開；長訊息截短顯示，完整內容可開啟詳情。上／下一步與儲存不與訊息爭用寬度。 |
| A05 捲動與定位 | 新頁／分類在 layout 完成後回到頂端；驗證錯誤定位欄位，鍵盤焦點移到 viewport 外時會捲至可見處。 |
| A06 Seed 還原 | 型別取自穩定 schema；支援數字、留白或「使用隨機值」，保存／重開後仍能恢復 null。裝置也能恢復 Windows 預設。 |
| A07 必要設定入口 | 加入麥克風／喇叭選擇與格式檢查，preview／正式 session 都依名稱與 host API 解析裝置。Local、Groq、Gemini、Edge、BlueMagpie 有專屬欄位及 key 來源說明。增加喚醒詞編輯／錄音測試、家人樣本匯入／錄製、角色／記憶編輯，以及 CLI 安裝／登入指南入口。 |
| A08 進階表單 | 預設只顯示所選服務；可包含其他服務，搜尋當前／全部分類、還原分類。提供 enum 選單、路徑瀏覽、多行文字與清單增刪。數字／型別錯誤有欄位名稱；已存在的無效數字、清單或裝置設定也能從 UI 修復。 |
| A09 檢查狀態與錯誤回復 | 確認頁分列模型查詢、裝置格式、辨識、麥克風錄音、試聽、喚醒詞與 key 來源。音檔辨識不會宣稱麥克風已測；沒有辨識到人聲也不標為通過。啟動失敗顯示階段與經遮罩原因，可返回相關設定。 |
| A10 更新／查詢／保存 | 查詢預設不更新；更新有獨立按鈕與階段提示，可取消並忽略舊結果。可在未查詢模型、未完成登入時保存有效設定；本次 wizard 內切換 backend 會保留已選模型。 |
| A11 文案與一致性 | 五步調整為 AI 服務、聲音與裝置、互動與使用限制、進階選項、確認與啟動。純文字模式收合未使用語音，仍可查看保留設定；移除空分類。字級提供完整 16–32 px 與預覽；額度說明 0 的意義、範圍與 Taipei 重置時區。 |

## 主要程式

- `ui/startup.py`：導覽、進階搜尋、錯誤定位、保存草稿、確認狀態與 model query 生命週期。
- `ui/audio_settings.py`／`audio_preview.py`：服務欄位、裝置選擇、錄音音量指示、前置檢查與分項測試狀態。
- `ui/settings_fields.py`／`core/settings_schema.py`：共用控制、型別與驗證 metadata。
- `ui/setup_managers.py`：本機喚醒詞／角色檔案編輯、格式與 token 驗證、聲紋匯入／錄製、原子寫入與內建指南視窗。
- `utils/audio_devices.py`／`startup_diagnostics.py`：裝置解析、資源檢查與錯誤遮罩。
- `core/audio_capture.py`／`audio_player.py`／`assistant.py`：正式 session 的裝置對接。
- `core/transcriber.py`：8 kHz 輸入的重取樣與自動語言對接。
- `tests/test_startup_usability.py`：本次問題與設定流程的回歸測試。

## 保存方式

一般草稿按「儲存設定」或啟動時寫入 private config；啟動準備失敗仍會 rollback 到此次準備前的設定。已明確儲存的設定不會因此消失。

Google key、喚醒詞／角色檔案、家人聲紋各有明確保存動作並立即生效。這些操作不隨 wizard 草稿取消而回復，畫面與指南均有說明。檔案寫入失敗會保留原檔；檔案未成功讀取時禁止覆寫。

## 驗證結果

- 完整一般回歸：**1,079 passed、25 skipped、3 warnings，31.28 秒**。Warnings 來自現有 Torch／SciPy／pkg_resources 相容性提示。
- UI 驗證組：**42 passed，50.88 秒**，包含 26 個 unit cases 與 **16 個 opt-in native Tk cases**；unit cases 與一般回歸重疊，不相加計算。
- native Tk 涵蓋服務區塊收合、BlueMagpie 啟用、捲動、footer、seed 保存／還原、無查詢保存、取消與舊結果隔離、Google key、錯誤回復及檔案操作。
- 以 Tk widget／window scaling 建立 **100／125／150／175% 等效尺寸**，在 logical 640×480 下遍歷五頁並注入長錯誤，檢查導覽按鈕的 mapping、寬度與視窗邊界。沒有改動 Windows 顯示設定。
- 最後補強既有無效清單／裝置設定的修復情境並單獨重跑：**1 passed**，屬上述 native case 的擴充。
- `git diff --check` 通過；新增／主要修改檔案經 strict UTF-8 讀取，無 replacement characters。

重跑一般回歸：

```powershell
cd ai_voice_assistant
.\venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

原生 UI 驗證請在獨立 PowerShell session、可互動的 Windows desktop 序列執行：

```powershell
cd ai_voice_assistant
$env:AI_GOVERNESS_NATIVE_TESTS='1'
$env:AI_GOVERNESS_CONFIG=Join-Path $env:TEMP 'startup-implementation-unused.json'
.\venv\Scripts\python.exe -B -m pytest -q -s -p no:cacheprovider tests/test_startup_usability.py tests/test_audio_startup.py::test_native_audio_settings_round_trip_stop_and_catalog_preserve_voice tests/test_google_credentials.py::test_startup_key_editor_saves_deletes_and_survives_page_changes tests/test_native_session.py::test_startup_draft_is_frozen_during_preparation
```

## 實機驗證限制

再次開啟隔離預覽後，Windows 畫面擷取仍回報 `CreateForMonitor 0x80070057`，重新取得視窗後桌面存取回報 `GetCursorPos 0x80070005`。因此未完成 screenshot 目視、色彩對比、實際鍵盤硬體、screen reader 或真人首次設定驗收；Tk geometry 與 callback 測試不代表這些項目已通過。

本次未使用真實 API 帳號執行音訊服務、錄製家庭音訊，或更新 CLI／安裝 BlueMagpie 環境。裝置實際音質、音色偏好、各提供者帳號／模型權限仍需在使用者環境以 UI 的錄音與試聽確認。安裝與登入維持明確引導及提供者介面，不內嵌自動登入。
