# UI v2 候選程式碼 Audit

日期：2026-10-04。範圍：此次 UI 重構的全部候選 source、launcher、設定標籤、白板 demo，以及實際重用的原生 UI 元件與接點。未執行整個 voice assistant、所有 CLI client 或私人 agent workspace 的全面 audit。

**結論：可繼續作為隔離候選版本進行 review；尚未符合正式交付條件。** 已修正下列可確認的缺陷，通過候選測試與原生 Edge smoke；真實服務、權威額度儲存、共用元件解耦與實機驗收仍是交付前的必要工作。測試通過不代表沒有其他缺陷。

## 已修正的缺陷

P1 表示可能造成錯誤狀態、資料／資源管理失敗或越過程式邊界；P2 表示可用性與驗證缺陷。

| ID | 等級 | 原問題與影響 | 修正與驗證 |
| --- | --- | --- | --- |
| A01 | P1 | model query 執行中改 backend，舊結果可能標成新 backend 可用 | query token、backend/update key、取消事件、30 秒 deadline；延遲結果與逾時測試 |
| A02 | P1 | 設定收集逐欄寫入；後面欄位失敗，前面已部分套用 | copy → parse → 整份 validate → commit；transactional collect 測試 |
| A03 | P1 | SessionConfig 選到的 backend/model/effort 沒進設定 snapshot；舊 Esc/F11 設定仍存在 | session_snapshot 統一覆寫選擇、退出固定 Alt+F4；不修改原草稿的測試 |
| A04 | P1 | float 可輸入 NaN/Infinity；quota 資料型別／日期／結構驗證不完整 | strict 型別、有限數值、整數範圍、日期格式、記錄大小、ModelInfo 檢查；舊日期的損壞記錄也拒絕 |
| A05 | P1 | 延遲播放 callback 使用可變 event，取消／重入後可能完成另一輪 | service token、callback owner、已完成 timer 移除；callback 中取消及 stale timer 測試 |
| A06 | P1 | activity／未來真實 backend callback 可能在背景執行緒操作 Tk | 所有外部事件走 thread-safe queue；主執行緒 bounded drain；背景 thread 回覆測試 |
| A07 | P1 | cancel/save/stop 任何一項拋出例外，後續 hook、Edge、timer、Tk 清理就跳過 | 每項資源獨立清理、錯誤收集、close 冪等；注入 service failure 驗證仍執行後續清理 |
| A08 | P1 | 額度存檔失敗後 close_board 再次存檔而拋錯，tick 停止 | session 內停用 HTML、無遞迴存檔、保留 tick；md 可繼續；disk failure 測試 |
| A09 | P1 | Edge launcher 父子 PID 推導不足以保證 cleanup 身分 | suspended CreateProcess → 私有 Job Object → resume；只 attach job members；失敗不執行程式；實測殺掉自己子程序但保留另一獨立程序 |
| A10 | P1 | HTML HTTP root 是 native source 目錄，遊戲能讀同目錄其他檔案；focus POST 未檢查來源 | 專用 web_assets/、loopback、固定 origin、Origin 驗證、原 CSP 與 traversal 防護；HTTP integration tests |
| A11 | P1 | game capture 沒在新 composer 取得焦點時釋放，可能吞掉 W/A/S/D 等字母 | focus flag、點擊釋放 capture、hook thread 不呼叫 Tk；composer capture regression test |
| A12 | P1 | service start 例外／缺少 completion 會卡在 THINKING，後續 queue 無法前進 | error event、bounded turn deadline、保留後續 queue；失敗不自動重送已提交的回合 |
| A13 | P1 | SetParent 失敗但 SetWindowPos 成功，可能誤認浮動 Edge 已嵌入 | attach 後驗證 GetParent；只接受 Chrome_WidgetWin_1；真實 Edge smoke |
| A14 | P1 | WindowProc 還原失敗時舊 helper 仍釋放 callback，可能留下無效原生 callback | 還原失敗保留 callback 到 HWND destroy；新增失敗測試與真實 guard install/remove 測試 |
| A15 | P1 | guard 啟動失敗只寫已停用的 logger，主畫面仍啟動 | 驗證 keyboard hook、WindowProc、input monitor；SetThreadExecutionState 檢查回傳；初始化非預期失敗清理並關閉 demo |
| A16 | P2 | tooltip 是獨立 Toplevel，timer／通知／scroll／library timer 可能殘留 | tooltip 改同視窗 child panel；追蹤通知等 timers；destroy 前取消 Tcl 剩餘 timers，保留各 widget 正常刪除 callback；重開視窗測試無殘留 timer 錯誤 |
| A17 | P2 | 圖片檔未關閉、白板未完成 layout 時取到尺寸 1、resize 不更新圖片 | context manager 複製圖片，先完成 layout，依容器 resize 保持比例；原 scene／人物素材不變 |
| A18 | P2 | smoke 使用 assert、沒檢查走完、與正常 demo 共用 lock | explicit checks、成功旗標、watchdog、獨立暫存 runtime／lock、ExitStack；提早退出不再假通過 |
| A19 | P2 | 啟動視窗固定 800 高可能超出工作螢幕；持續對話無 widget 上限 | 初始尺寸依 screen clamp，小寬度隱藏重複摘要；聊天最多保留 200 個訊息 widget |
| A20 | P2 | 停用的 Web 草稿含不存在的 script 與過時退出操作 | 移除舊 Web 程式碼與素材，只留歷史說明；候選 UI 只有 CustomTkinter |
| A21 | P2 | Markdown 額外註冊的 theme callback／textbox timers 未由原 renderer 完整釋放 | OwnedMarkdownRenderer 只清理由這次 render 新增的 callbacks 與 widget 所屬 timers；close board regression test |
| A22 | P1 | 125% 系統 DPI 下 Tk fullscreen 取到虛擬尺寸，1920×1200 螢幕只覆蓋 1536×960 | fullscreen 後重新取得 Tk 重建的 wrapper HWND，依 rcMonitor 原生邊界 SetWindowPos；Configure 後校正，保留 fullscreen、focus、z-order；視窗與 client 實測皆為 1920×1200 |
| A23 | P1 | 啟動選單 destroy 後 DropdownMenu scaling callback 殘留，DPI／scaling 變動可觸發 TclError | OwnedComboBox 在 destroy 前只移除自身 menu scaling callback，不修改套件；app window scaling 1／1.25／1.5／2 回歸測試 |
| A24 | P1 | 直接跳最後啟動會因沒有 model query 回第一步，但後續逐步按「下一步」仍跳過查詢而反覆失敗 | 第一步「下一步」自動查詢，成功才前進並初始化 effort；失敗／逾時／invalidate 清除待前進狀態、恢復按鈕；手動 query 留在第一步。保留被點擊按鈕直到 click animation 完成；跳步後實際啟動、失敗重試、取消／stale result 測試 |
| A25 | P1 | Markdown 外包 CTkScrollableFrame，內部 textbox 保持預設高度，僅佔部分白板 | 移除重複捲動容器，原 renderer 直接 pack fill/expand 於 board_body；實測 widget／body 都為 1308×915，長文 viewport 測試 |
| A26 | P1 | 新版漏掉白板可見時暫停 presence 詢問；queued activity 仍可能觸發收音 | 共用 pause 條件包含 board_visible、phase、mute；show/hide/restore/close 同步，on_activity 再拒絕可見白板事件；三格式與收音／朗讀狀態測試 |
| A27 | P1 | Edge 自繪 app titlebar 留在 client 區，移除 Windows styles 仍露出瀏覽器按鈕；resize 可能沿用已過期的初始化 deadline | 依 Chrome_RenderWidgetHostHWND 的 client 與 host 的實際邊界裁切 browser chrome，非固定 DPI offset；內容完全填滿容器才標示 attached／計時，後續 resize 校正並給予新的 bounded 等待期限；真實 Edge、負座標 viewport 與 deadline 測試 |
| A28 | P2 | Markdown 隱藏／展開重新建立元件，閱讀位置丟失 | 非 HTML 格式直接恢復現有 view，保留文件／圖片物件與 scroll；長篇閱讀位置 regression |
| A29 | P2 | 朗讀已開始後才開 HTML，初始音效未 duck，須等待下一次 refresh | 新 renderer 在 show 前同步目前朗讀狀態；建立時的 duck 狀態測試 |
| A30 | P1 | 背景 attach 持有 lock 呼叫 SetParent/SetWindowPos，可能與 Tk 的同步視窗訊息互相等待；未 mapped／未完成的 Chrome shell 也可能被嵌入 | worker 只尋找已建立 web render child 的 Job-owned 視窗，確認 host visible 後 post 至 UI thread；UI callback 重新驗證 generation、PID 與 Job membership 再嵌入；取消／dispatch regression，全螢幕 smoke 改為真正啟用 guards |
| A31 | P2 | 已耗盡的每日額度跨重啟保留，但 Review HTML 按鈕仍看似可用，僅顯示短暫提示，容易被誤認成開啟失敗 | Review 列常駐剩餘時間／耗盡或儲存失敗原因，HTML 按鈕同步停用；demo 重設先結算時間並透過統一存檔流程，失敗不解鎖。跨重啟封鎖／保留 Markdown、重設後 HTML callback、零上限與存檔失敗測試；以既有耗盡 runtime 實測重設後真實 Edge attach 與 guards |
| A32 | P2 | 文字輸入框雖有自動捲軸，但 thumb 與背景同色，使用者難以看見可拖曳範圍 | 調整 thumb／hover 顏色；原生檢查 200 段 Markdown 與 100 行輸入內容均自動顯示垂直捲軸，呼叫捲軸實際 command 可移動閱讀位置，縮成短內容後兩者自動隱藏；未修改原 renderer 或套件 |
| A33 | P2 | 啟動視窗雖限制尺寸，仍可能開在偏下位置，底部操作列超出工作區 | 依 native monitor work area 校正位置與尺寸，僅在 startup 執行；job 追蹤／close 取消；實測視窗與 footer 位於工作區內，回歸測試 |
| A34 | P2 | 原生 dropdown 與欄位寬度不一致，箭頭使用 font glyph，選取狀態不清楚 | 同視窗圓角 popup、統一圖示箭頭、目前值勾選與 hover／focus 色；方向鍵／Enter 選取、Escape／outside click／resize／focus out 收合。僅移除 popup 自己註冊的 root callbacks，更新值／disabled／destroy 也關閉；keyboard catalog invalidation 與 bindings 保留回歸、實機按鍵驗證 |
| A35 | P1 | 大型 catalog 一次建立數百個選項元件，長清單測試出現視窗與後續操作拖慢 | 保留完整 values，僅建立最多 11 個可見 row 循環繪製；Canvas 保留全清單 scroll range，使用測量的 native row pitch 避免 DPI rounding 累積。500 模型最後一項可見／可選、清理測試通過，單項驗證約 1.1 秒 |
| A36 | P2 | tooltip 使用 physical 距離作為 CTk place 座標，DPI scaling 下可能偏移 | 換算為 tooltip 的 widget scaling 後再定位，維持同視窗 child panel，保留 timer 清理測試；未新增 Toplevel |
| A37 | P2 | 原生 UI 測試在首次 mainloop 前送出 query 並安排短 quit timer，CTk 的 Windows 標題列初始化會先執行 nested update，可能提前消耗 quit 而讓測試停住 | setUp 先映射初始視窗，再執行測試操作與計時；不修改程式事件迴圈或套件。完整 67 tests 通過；白板回歸同時檢查恢復按鈕可見、位於舞台左下、未越界，以及恢復後隱藏按鈕／保留閱讀位置 |
| A38 | P1 | 新版 toolbar 高度在 125% DPI 下觸發 Edge client 高度於目標 ±1 px 來回，要求精確相等導致尺寸校正逾時 | 左上角仍須精確對齊，右／下允許最多 2 個 native pixels 的 overscan，由 parent 裁切；不得接受任何未填滿、原點偏移或更大 overscan。新增穩定覆蓋／禁止缺口與偏移測試；Windows／HTTP 11 tests、真實 Edge fullscreen attach／hide／restore／resize／expiry smoke 通過 |

額度存檔使用 temp file、flush、fsync、atomic replace；失敗保留前一筆有效記錄並移除 temp。正常顯示每 250 ms 觀察一次 attach／visibility／desktop 可用狀態；正常關閉／隱藏強制結算與存檔，播放中每秒存檔。新 attach 不計啟動等待；偵測到鎖屏／secure desktop 或最小化時暫停計時。

Windows Job Object 的程序身分與關閉語意依 [Microsoft Job Objects 文件](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。新增的 Windows API wrapper 所有 pointer／HANDLE 參數明確宣告，launch 不經 shell，handles 不繼承。

HTML 仍使用隔離 Edge App profile，將自繪 titlebar／資訊列裁切到 host 邊界之外，只讓 web render viewport 出現在白板內。未改用 Edge kiosk，因為其 [InPrivate 行為](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-configure-kiosk-mode) 會影響本 demo 隱藏時結束程序、恢復時使用 localStorage 的保存流程。這是 Windows／此 Edge 版本驗證過的候選 host，正式版仍需測試其他 Edge 版本與多螢幕 DPI。

## 正式交付阻擋項目

| 項目 | 現況與必要工作 |
| --- | --- |
| 真實 CLI／音訊 | DemoCatalog 回傳明確標示的虛構模型；沒有更新 CLI、驗證 auth、真實 query、STT、TTS。必須逐 backend 實作 query/update/cancel/timeout，接入正式 pipeline 的仲裁、播放停止確認與收音生命週期。四種 input/output 能力須實測。 |
| 共用元件 | MainWindow 仍繼承 LegacyWindow 而跳過其 __init__，依賴部分 private helpers/config 接點。整合前抽出 guard／host／event components，移除這個過渡耦合；不可直接用這個繼承方式替換正式 UI。 |
| 完整設定 schema | 現有驗證涵蓋型別、有限數值及候選消費的安全限制。尚缺各 backend/audio enum、路徑與裝置可用性、跨設定相依驗證、private overrides 儲存、secrets 管理與未知 key migration。 |
| 額度權威 | demo 是同 runtime 單一 instance 的 JSON，沒有跨帳號交易與 ACL／防篡改。正式 service/manager/tool 必須共同拒絕超額 HTML，避免只擋 UI；家長調高額度的授權策略待確認。 |
| 異常關機與時間 | 正常 polling 誤差約一個觀察間隔，但 Tk 主執行緒長時間卡住時沒有硬性 250 ms 上限。系統斷電／強制 kill 最多可能失去最後未提交的一秒使用量；quota file 不保證 power-loss 下的磁碟目錄耐久性。鎖屏／睡眠與午夜的組合仍需 WTS/power notifications 驗證；本輪沒有實際鎖機測試。 |
| 任意 HTML 狀態 | 已實機驗證固定 demo 作答後隱藏／恢復，題目與完成題數保留；遊戲依 localStorage checkpoint，並非任意 HTML 記憶體狀態恢復。任意遊戲的保存方式與異常關閉仍需驗證。當固定 port 被占用時明確失敗，不換 origin。 |
| 初始化／fatal UX | 額度讀取／初次存檔錯誤留在啟動 UI；其餘非預期初始化／callback 錯誤清理後關閉並留下 diagnostic。正式版仍需可恢復的 rollback／重試與家長錯誤流程。 |
| 全螢幕與視覺 | 已實測 hook/WndProc、真正啟用 guards 的 fullscreen／Edge smoke，並在前景 QA 視窗檢查 Markdown／HTML。HTML 取得焦點時 F11/Esc 維持全螢幕，Alt+F4 可關閉。仍缺實際 100–200% OS DPI、多螢幕、中文 IME、其餘快捷鍵與長時間運作驗收；局部畫面檢查不能證明商用品質的視覺全部完成。 |
| 長訊息／紀錄 | preview 只保留最近 200 個 widgets，沒有永久對話紀錄。正式 streamed text 需另定 API，不能把每個 token 當成完整訊息新增。 |

這些是已知尚未完成的交付工作，不是本輪測試失敗，也不代表使用者已批准整合。

## 驗證與可重現指令

```powershell
.\ai_voice_assistant\venv\Scripts\python.exe -B -m unittest discover -s prototypes/ui-v2/native -p 'test_*.py' -v
.\ai_voice_assistant\venv\Scripts\python.exe -B prototypes/ui-v2/native/main.py --smoke-html --smoke-fullscreen --review-tools
cd ai_voice_assistant
.\venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_main_window.py tests/test_html_whiteboard.py tests/test_global_input_monitor.py tests/test_animation_controller.py tests/test_public_html_whiteboard.py
```

- 候選測試共 69 tests：本輪先完成既有 67 tests，再於 DPI 裁切修正後完成 Windows／HTTP 11 tests（含新增 2 tests）。包括真正 Windows Job／HTTP server／原生 guard，以及故障注入、query 競態、thread marshal、queue、額度、cleanup。另含白板填滿、活動暫停、閱讀位置、初始 duck、內容裁切、UI thread attach／取消、ownership 重新驗證、resize 等待期限，以及 Review 額度耗盡／重設狀態。
- 美化驗證：實際檢查 Markdown 主畫面、圖示狀態與圓角設定選單；方向鍵展開／移動、Enter 切換 backend 並使舊模型失效、Escape 收合、Alt+F4 關閉 QA 視窗。新增 startup work area、選單清理／既有 bindings 保留與 500 模型測試；美化後重跑真實 fullscreen／Edge attach／restore／resize／expiry smoke 通過。
- 主畫面色彩調整：深藍頁首、靜態細線／色塊、霧藍工具列、暖米色訊息與鼠尾草綠圖示，沒有新增常駐文字或動畫。實際全螢幕點擊白板隱藏、舞台左下恢復、Alt+F4；QA callback／cleanup errors 均為空。原背景與人物素材未修改。
- 既有 demo runtime 驗證：今日 used=1800.063 秒，30 分鐘上限下正確封鎖 HTML 並保留 Markdown；經實際 Review 重設與 HTML 按鈕 callback，真實 Edge 成功 attach，keyboard／screen guards 與 activity pause 正常。只重設獨立 demo 用量，不更動正式設定。
- 原元件回歸：前輪 170 tests（main_window 131，其餘重用元件 39），本輪未修改其 source。未宣稱跑過整個專案 test suite。
- Native Edge smoke：設定五頁、主畫面 fullscreen native window／client 邊界、朗讀狀態／mic 打斷、md hide/restore、真實 Edge attach/hide/restore／resize、到期關閉、禁止重新開 HTML、md fallback、cleanup。加上 --smoke-fullscreen 時，使用一般 start_session 全螢幕路徑，實際安裝 keyboard hook 與 screen guard，檢查 handles；未使用該參數時仍為視窗 smoke。
- 每份候選 Python 檔 strict UTF-8／AST／compile 檢查；JSON 與 HTML strict UTF-8 讀取。沒有以終端中文顯示亂碼判定檔案損壞。
- .runtime/、Edge profile、diagnostic、quota 都是 gitignored；preview 使用獨立 config temp directory，不讀 private config 或寫正式 logs。

## 檔案範圍

逐份檢查 native/ 的 bootstrap.py、domain.py、services.py、startup.py、widgets.py、main_window.py、html_host.py、markdown_host.py、fullscreen_host.py、main.py、validation.py、windows_job.py、window_environment.py，以及四個 test_*.py；field_labels.json、web_assets/game.html、兩個 .bat launcher 與文件同步檢查。

原元件檢查包含 AnimationController 的載入／resize／timer／destroy；GlobalInputMonitor 的 widget/global/thread 路徑；LegacyWindow 的 event queue、keyboard/screen/display guards、白板鍵盤橋接與 Markdown renderer；HtmlWhiteboardRenderer 的 loopback/CSP/path boundary、attach/focus/input/server/browser teardown。未變更上述原始 source、正式入口或原素材；所有候選變更留在 prototypes/ui-v2/。
