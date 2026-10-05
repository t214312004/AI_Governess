# 正式 UI 整合與稽核紀錄

> 此為 2026-10-05 正式 UI 整合的驗證快照；模型數量、外部 CLI 狀態與測試數字只代表當時。日常操作見 [UI README](../ai_voice_assistant/ui/README.md)，本次文件／提示詞核對見 [文件 audit](documentation_audit_2026-10-05.md)。

## 整合前存檔

`53b2eab03ebffc9352f2b60bd301e2d71e63746e` — `Save approved native UI prototype before production integration`。

此 checkpoint 已包含整合前所有可提交的修改，通過 `scripts/pre_git_audit.ps1`，並 push 至 `origin/main`。當時正式入口仍使用原有 UI；候選 UI 可從此 checkpoint 取回。正式整合通過後，依使用者要求刪除候選 UI 的獨立 demo 目錄。

## 正式路徑與保留功能

| 項目 | 正式實作／對接 |
| --- | --- |
| 一般／Debug 啟動 | `start.bat`、`debug.bat` 都進入 `main.py` 的初始設定視窗 |
| 初始設定預設值 | `Config.snapshot()` 完整複製 public defaults 與當下 private overrides；包含未知本機 keys，沒有將私人值寫進 public defaults |
| 設定提交 | `Config.apply_snapshot()` 原子寫入 private config；寫入失敗保留舊檔案與記憶體，準備失敗回復設定，可再次啟動 |
| 真實啟動 | 設定確認後才建構 `VoiceAssistant`，執行 `prepare_for_gui()`，再建立正式 session UI |
| UI callbacks | 正式 session UI 呼叫原有 constructor，保留狀態、串流訊息、清空歷史及排程 callbacks 與 UI event queue |
| 語音與 backend | 沿用既有 STT、wake word、speaker recognition、LLM streaming、TTS、cancel、session refresh 與 heartbeat 流程 |
| 全螢幕 | Windows monitor bounds／DPI 校正；僅 Alt+F4 退出，保留 keyboard hook、screen guard、display awake 與 screensaver block |
| 角色舞台 | 原有 AnimationController、背景與所有 state 素材；素材檔案零修改 |
| 使用者活動提示 | 保留原有前景活動條件；白板顯示期間暫停，隱藏／關閉後恢復 |
| 排程 | 沿用原有 schedule panel、CRUD、報告與通知，不移除既有排程功能 |
| 白板 | 沿用 manager、工具協定、Markdown／image renderer、HTML CSP 與 audio／input bridges |
| 重開白板 | 關閉主程式不清除 active whiteboard state；重開時恢復同一份 Markdown、圖片或 HTML，明確關閉白板才清除內容 |

## 輸入、輸出與待送訊息

- 初始設定固定 backend、model、effort、輸入與輸出方式；主畫面不提供設定切換。
- 語音輸入模式可手動 mute；固定文字輸入無法 unmute。語音播放中顯示自動 mute，按 unmute 會打斷並收音。
- 播音 mute 獨立於麥克風；停止當前音訊，不取消 backend 的文字回覆。mute epoch 防止快速解除靜音後舊音訊重新播放。
- 文字送出使用 FIFO，最多 10 則、每則 8,000 字；busy／播放中保留待送項目，只有 backend 接受後才移出。可取消單則或打斷並送出。
- 固定文字輸入不初始化 VAD、Whisper、wake word 或 speaker recognizer，也不啟動麥克風收音；固定文字輸出不啟動音訊播放。

## 模型與 effort

模型識別字由 CLI 回報，正式 UI 沒有內建模型清單。更新與查詢共用取消與逾時機制，啟動的 process tree 由本次 Windows Job 管理，關閉不影響其他 CLI／Edge 程序。

ACP 使用 CLI 回報的實際 config option ID，支援分組 options；每次切換模型及建立新 session 後，以最新能力重新驗證 mode 與 effort，並接收目前 session 的能力更新。對照 [ACP session configuration](https://agentclientprotocol.com/protocol/v1/session-config-options)。Claude 的查詢使用 `-p` 與 stream-json initialize，對照 [Claude CLI reference](https://code.claude.com/docs/en/cli-reference)。

| Backend | 查詢與 effort 對接 | 實機狀態 |
| --- | --- | --- |
| Antigravity | `agy models`、`--help`；從 CLI 回報的具體模型變體限制相容 effort | 18 個模型查詢成功；正式 UI 真實對話與 Edge TTS 成功 |
| Codex | app-server `model/list` 分頁與 `supportedReasoningEfforts`；查詢不建立對話 thread | 5 個模型及 effort 查詢成功 |
| Claude Code | stream-json initialize control response 的 models／supportedEffortLevels | 本機未完成真實對話驗證 |
| OpenCode | ACP model options；切換 model 後重新讀取 thought_level；`mode` 保留為獨立操作模式 | 協定回歸測試通過，未完成真實對話驗證 |
| Grok | ACP 模型與能力回報；只提供實際回報的推理等級 | 協定回歸測試通過，未完成真實對話驗證 |

本機 Codex 的既有全域 `service_tier` 設定與已安裝 CLI 出現相容性問題。模型查詢已成功，但完整 Codex 對話尚未實機驗證；本次未修改 CLI 的外部全域設定。其餘未驗證 backend 仍需具備可用安裝、登入與服務權限。

## 白板額度與原生 host

- 每日 HTML 用量在 private state 持久保存、使用 process-safe lock 與原子寫入；重開程式不重置，Taipei 換日重置。系統時間倒退時仍持續消耗最後記錄日期的額度，不額外授予額度。
- 只計入實際附著、可見的 HTML；隱藏、關閉與鎖定桌面暫停。Windows unbiased uptime 排除 sleep／hibernate。
- 到期關閉 HTML；manager／工具端也會拒絕 HTML，Markdown 與圖片仍可顯示。損壞或無法寫入額度紀錄時停用 HTML。
- HTML 用 render HWND 裁掉 Edge chrome，保留原有網路限制；hide 卸載 host，restore 使用相同 localhost origin／profile 保留 localStorage。未自行保存的頁面記憶體狀態不保留。
- Markdown timer／appearance callbacks、HTML Job、input monitor 與 Windows guards 都在 root destroy 前清理，避免重開 Tk 時留下無效 callback。

## 驗證結果

- 完整回歸：**941 passed、7 skipped**。七個 skipped 是下列另行執行的原生測試。兩則 warning 來自既有第三方套件的 deprecation。
- 原生 Windows／Edge 測試：**7 passed**。驗證 monitor bounds、guards、長 Markdown 填滿白板與捲動、多行輸入捲動、左下恢復、保留 Markdown widget、待送清單高度、實際 Edge 附著／卸載／恢復、額度倒數與到期、到期後顯示 Markdown、三種內容重開恢復、Markdown 解析失敗後的清理，以及啟動設定凍結。
- 真實 `main.py` 啟動：初始視窗 → CLI 查詢 →準備 →全螢幕成功。跳至最後一步尚未查詢時可返回完成並正常啟動；F11 無法退出，Alt+F4 正常清理關閉。
- 真實 Antigravity／Edge TTS：中性測試訊息得到成功回覆；播放期間打字與送出成功，待送訊息在 SPEAKING 結束後才交給 backend，並得到下一筆成功回覆。
- 設定與取消回歸包含完整本機 keys 保留、寫入失敗、rollback 新增 keys、準備／清理失敗後重試、mute 不取消 backend、FIFO busy 保留、CLI 取消與 descendants 清理。
- 本次沒有實機重新錄音驗證 Whisper／speaker recognition；其既有自動化回歸均通過。

原生測試採 `-s`，避免 Windows Tcl 與 pytest fd capture 在同一程序建立下一個 Tk root 時互相影響。正式的初始視窗接主視窗流程亦已在一般 Python 程序驗證；測試保留真實 fullscreen／keyboard guards。

## 整合後追加 audit 修正

- 準備啟動時凍結所有設定與導覽控制；準備失敗恢復各控制原先的狀態，包含第一頁停用的「上一步」。
- HTML attach／reload 的延遲檢查綁定 renderer generation；隱藏、換內容與關閉時取消，避免舊 callback 誤報。使用者正在輸入時不搶走焦點。
- Markdown 部分建構或解析失敗時清理 widget 與 timer；圖片及錯誤 fallback 填滿白板。
- 文字送出與語音啟動競態回報 busy；backend 例外保留 FIFO，輪詢 callback 例外不會讓後續輪詢永久停止。
- Windows Job 終止後等待 descendants 釋放繼承的檔案 handle，再清理暫存資料；已持有 Job 的 CLI 關閉與緊急停止不回退到 PID-based taskkill。
- 模型查詢只建立空白暫存 context，覆蓋使用者配置的私人指令與記憶路徑。修正 Claude print mode 與 ACP actual IDs、grouped options、session refresh／model change 後的過時能力。
- 用量紀錄在啟動後損壞也會停用 HTML；拒絕非標準日期／未知 schema version。修正系統日期倒退後停止扣除用量的漏洞。
- 程式結束僅釋放白板 renderer；不清除持久內容。原生測試以新的 WhiteboardManager 重新讀取並恢復三種白板內容與既有 HTML 用量。

## 公開內容與 demo 隔離

- 正式入口不 import `prototypes/`；未帶入 DemoCatalog、模擬回覆 controller、MD／image／HTML review 按鈕或額度 reset 按鈕。
- 獨立 UI demo 的 tracked 檔案已全部刪除；共用元件已移到正式 `ui/`。既有公開 HTML 教材示範保留，這是原本的白板功能。
- 本機 QA config、workspace、logs 與 audit 輸出移至 repository 外的系統暫存資料夾；repository 內不再保留 demo code 或其 runtime 殘留。
- 新增／修改公開文字檔通過 strict UTF-8；Python 通過 AST parse，JSON 通過 parse，diff whitespace check 通過。
- 待提交新增內容與本機非公開設定字串比對，並掃描 credentials、私人 home path、email 及 demo runtime imports，沒有發現混入。
- `config.local.json`、個人記憶、logs、語音樣本、模型、archive、runtime state 與 venv 均未納入此次整合。
