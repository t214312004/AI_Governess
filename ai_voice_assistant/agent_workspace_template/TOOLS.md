---
file name: TOOLS.md
role: tool_reference
default_load: false
last_updated: 2026-10-05
---

> 公開 template：僅描述介面與操作契約；本機外部工具須檢查可用性後才操作。


# 工具操作參考

先依 `AGENTS.md` 判斷身份、必要性與授權。本檔描述操作契約，不保證當前所有外部工具、裝置或 app 都可用；執行前確認入口，執行後讀結果。

所有相對路徑與指令以下以 `agent_workspace/` 為工作目錄；Python 工具使用 `..\venv\Scripts\python.exe`，避免落到其他環境。

專案內建的是本機 CLI 入口：whiteboard、schedule 與 camera wrapper，由 LLM backend 的 shell 執行，不是每個平台都自動提供的同名 function tool。讀寫檔案、web search、看圖片、瀏覽器控制等由當前 CLI／本機安裝決定；opencli、Chrome Bridge 與 Windows 裝置能力不是 app 保證內建。工具無法呼叫時說明限制，不宣稱已操作 UI 或已看見畫面。

## 授權與兒童入口

- 查詢、必要讀檔、整理及任務所需螢幕截圖可直接做；不讀與任務無關的 private files，不將私密內容放到共享畫面。
- 瀏覽器與網站互動、音量、亮度、其他系統設定依家長或明確授權使用者的要求執行；敏感動作依 `AGENTS.md` 的具體授權規則。
- 攝影機須現場家長明確同意。截圖限當前任務、存暫存或 `scratch/`，不長期保存或外傳；照片需要保留時放 `tools/camera/camera_capture/`。
- 孩子可要求顯示 已驗證並在 `GAMES.md` 列明的既有、離線 HTML 遊戲，或製作／修改同類低風險作品；以 whiteboard `show-html` 呈現，不擴張到開外部瀏覽器或系統控制。
- 獨立 GUI 白名單需在 private workspace 驗證後列入；公開 template 不預設私人程式。每個入口需說明啟動命令、可用功能、停止方式與授權。記憶展示只能用安全展示資料，不讀真實家庭記憶。

## 查詢、瀏覽器與裝置

- 查詢只補當前必要資訊，先找相關文件，編碼規則見 `AGENTS.md`。
- `opencli` 網站控制依賴 Chrome Browser Bridge；先檢查 Chrome 與外掛，使用 `opencli --help`、`opencli browser` 確認當前語法。舊驗證紀錄不等於現在可用；未連接就明說限制。
- 需要啟動 Chrome 可用 `Start-Process chrome -ArgumentList 'about:blank'`；關閉只操作任務對應視窗，不結束所有瀏覽器程序。
- YouTube 點擊失效時，只有確認已聚焦正確頁面才用播放快捷鍵，避免向其他視窗送鍵。
- 教育部筆順網既有入口：`https://stroke-order.learningweb.moe.edu.tw/searchW.jsp?WORD={國字}`。家長詢問筆畫時可開啟；網址若失效應重新確認官方入口。
- 音量可透過 Windows 音量鍵控制。鍵碼提高 `0xAF`、降低 `0xAE`、靜音 `0xAD`；key down/up 配對。每格約 2% 是舊觀察，不能當精準 API；讀不到目前值就不宣稱精確百分比，也不為微調先歸零再大幅提高。
- 亮度可使用 WMI，裝置不支援則明說：

```powershell
(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness
Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{Brightness = 50; Timeout = 0}
```

- 主螢幕截圖可用 `System.Windows.Forms.Screen` 與 `System.Drawing.Bitmap` 的 `CopyFromScreen`，完成後 Dispose；先確認儲存路徑，照片與截圖不代表持續視覺感知。

## 攝影機

入口 `tools/camera/camera.cmd`，詳細參數見 `tools/camera/README.md`。沒有拍照同意時，不執行 capture。

```powershell
.\tools\camera\camera.cmd list-devices
.\tools\camera\camera.cmd list-resolutions --device "裝置名"
.\tools\camera\camera.cmd capture --resolution medium
.\tools\camera\camera.cmd capture --device "裝置名" --resolution 1920x1080 --output ".\tools\camera\camera_capture\test.jpg"
```

解析度可用 `auto`、`max`、`high`、`medium`、`low`、`fhd`、`hd`、`vga` 或 `WIDTHxHEIGHT`，依實際 `--help` 確認；預設 nearest fallback。只描述任務必要內容，不轉述照片中的無關個資。

成功 JSON 的 ok: true 與 output_path 表示已存照片；ok: false／非零 exit code 表示失敗。capture 是單張拍照，不是直播或持續監看；要描述照片需再使用實際可用的圖片讀取能力。沒有 camera／DirectShow 裝置時不能承諾拍到。

## Schedule tool

工具是 `tools/schedule_tool.py`。建立、修改、刪除、啟停、草稿確認／取消、undo 與報告 availability 都用它；不直接改 schedule、draft、run 或 report JSON。持久化 state 在 workspace 外，由 `ScheduleManager` 唯一寫入。

```powershell
..\venv\Scripts\python.exe tools\schedule_tool.py draft-create --payload tool_payloads/schedule/<payload_id>.json
..\venv\Scripts\python.exe tools\schedule_tool.py draft-confirm --draft-id <draft_id>
..\venv\Scripts\python.exe tools\schedule_tool.py draft-cancel --draft-id <draft_id>
..\venv\Scripts\python.exe tools\schedule_tool.py draft-update --draft-id <draft_id> --payload tool_payloads/schedule/<payload_id>.json
..\venv\Scripts\python.exe tools\schedule_tool.py undo --operation-id <operation_id>
..\venv\Scripts\python.exe tools\schedule_tool.py list
..\venv\Scripts\python.exe tools\schedule_tool.py edit --schedule-id <schedule_id> --payload tool_payloads/schedule/<payload_id>.json
..\venv\Scripts\python.exe tools\schedule_tool.py delete --schedule-id <schedule_id>
..\venv\Scripts\python.exe tools\schedule_tool.py enable --schedule-id <schedule_id>
..\venv\Scripts\python.exe tools\schedule_tool.py disable --schedule-id <schedule_id>
..\venv\Scripts\python.exe tools\schedule_tool.py reports-list --recipient <recipient>
```

建立 payload 外層必須有 draft；下例使用展示身份，實際 created_by 與 reminder_for 依已確認的使用者填寫，不以聲紋猜測取得敏感授權：

```json
{
  "created_by": "PersonA",
  "original_text": "每天晚上八點提醒我喝水",
  "draft": {
    "title": "喝水提醒",
    "task_prompt": "提醒我喝水。",
    "created_by": "PersonA",
    "reminder_for": "PersonA",
    "trigger": {"type": "daily", "time": "20:00", "timezone": "Asia/Taipei"},
    "report": {"required": false}
  }
}
```

- once 用未來的 ISO run_at 或 date + time；daily 用 time；weekly 再填 weekdays（Monday=0 至 Sunday=6，至少一天）。目前不開放 interval；miss policy 可用 skip、run_late、defer_until_idle。
- edit payload 是排程欄位 patch；draft-update 可用欄位 patch 或外層 draft。需要報告時填 report.required: true、recipient、必要的 sensitive；只有提醒與 LLM 摘要型排程，網站、系統、相機、登入、付款與外部工具任務會被拒絕，不可改寫措辭繞過。
- SchedulePoller 與 heartbeat 開關獨立；只有 app 開著且待機時執行，不是 Windows 排程服務，也不會自動開機或在程式關閉時通知。一般 heartbeat 是只讀 context；已確認排程會收到獨立的系統任務提示。

- Payload 只寫 `tool_payloads/schedule/`，它是暫時輸入，不是 state。
- 讀 `status`，以 `message_for_user`、`confirmation_question`、`clarification_question` 對家人說明，不朗讀 raw JSON。
- needs_clarification 若是 payload／路徑錯誤先自行修正；只有缺少使用者需求才問。這些 status 不是已完成；needs_confirmation 問工具的確認問題並等待。確認呼叫 draft-confirm、修改呼叫 draft-update、取消呼叫 draft-cancel，不可自行另建類似排程。
- 低風險自我提醒可直接回傳 `created` 與 undo 時窗。以該動作的成功狀態及結果判定完成，不尋找不存在的固定 `success` 字串。
- 涉及他人、向家長報告、敏感內容、外部／系統／camera／browser／payment／login 或授權不清時，遵守工具的釐清與確認流程。
- 只有最新一期待交付報告有用時設定 `report.keep_latest_report_only: true`；否則保留預設 false。
- 報告正文、接收者匹配、注入與 delivered 標記由 app 管理。此處只能查 availability，不用工具或 JSON 讀寫取得正文、標記 delivered，亦不把正文帶入無關對話。
- reports-list --include-body 與 report-deliver 是相容入口，固定回傳 blocked，不能拿來交付。預設 draft 20 分鐘過期，低風險建立的 undo 時窗 2 分鐘；以結果中的 draft_expires_at／undo_until 為準。

## Whiteboard tool

唯一入口 `tools/whiteboard_tool.py`。當使用者要求畫面顯示，或資訊適合保留為可讀表格、筆記、圖片、互動遊戲時使用；短回答不必開白板。

```powershell
..\venv\Scripts\python.exe tools\whiteboard_tool.py show-markdown --payload tool_payloads/whiteboard/<payload_id>.json
..\venv\Scripts\python.exe tools\whiteboard_tool.py show-image --payload tool_payloads/whiteboard/<payload_id>.json
..\venv\Scripts\python.exe tools\whiteboard_tool.py show-html --payload tool_payloads/whiteboard/<payload_id>.json
..\venv\Scripts\python.exe tools\whiteboard_tool.py reload --content-id <content_id>
..\venv\Scripts\python.exe tools\whiteboard_tool.py hide --content-id <content_id>
..\venv\Scripts\python.exe tools\whiteboard_tool.py restore --content-id <content_id>
..\venv\Scripts\python.exe tools\whiteboard_tool.py close --content-id <content_id>
..\venv\Scripts\python.exe tools\whiteboard_tool.py close
..\venv\Scripts\python.exe tools\whiteboard_tool.py status
..\venv\Scripts\python.exe tools\whiteboard_tool.py get-content --content-id <content_id> --max-chars 4000
```

Payload 都放 `tool_payloads/whiteboard/`：

```json
{"title":"短標題","markdown":"# 標題\n\n重點"}
```

```json
{"title":"短標題","markdown_path":"tool_payloads/whiteboard/<file>.md"}
```

```json
{"title":"圖片標題","image_path":"tool_payloads/whiteboard/assets/<image>.png","alt_text":"圖片內容"}
```

```json
{"title":"遊戲標題","html_path":"apps/<app_name>/index.html"}
```

- 文字用 Markdown，只放短段、標題、粗體、小表格；不放 raw HTML、JavaScript、iframe、form、remote image、Markdown 圖片、外部連結或 `file://`。需要看網址時只列純文字，不依賴可點連結。
- Image/Markdown 只供顯示；HTML 需已存在 `apps/` 下，可用 JS、Canvas、鍵盤／pointer／touch、Web Audio 與 `localStorage`，網路封鎖。示範入口 `apps/html_whiteboard_demo/index.html`。
- 同時僅一個 active item，`show-*` 會取代；不要直接改 `whiteboard_state/`。
- 看狀態用 status，即使 active: false 也有 html_quota；active 時 hidden 表示期望的隱藏狀態。html_quota.daily_limit_seconds、used_seconds、remaining_seconds 是秒數，available 與 status 說明能否開啟 HTML：available、exhausted、disabled（每日額度為 0）、error（讀寫失敗，剩餘時間為 null，不能當成 0）。
- HTML 被拒絕時讀 block_reason、html_quota 與 message_for_user，用口語說明是額度用完、設定停用或紀錄錯誤；可改用 Markdown／圖片。預設每日 30 分鐘，Taipei 00:00 換日；隱藏、關閉、鎖定與睡眠不扣額度。不改用量 JSON、不重啟繞過額度，也不自行更改本次設定。
- status 是最近保存的 state／用量，不能保證 renderer 附著或得知即時 DOM。需要內容才用 get-content：Markdown 回傳本文與截斷資訊，image 回傳 metadata／路徑，HTML 只回入口路徑／app 資訊，不回原始碼、截圖或遊戲當下進度。需要修 HTML 時再讀回傳的原始檔路徑。
- 圖片的 absolute `image_path` 是短暫唯讀副本，修改後另存 assets，再 `show-image`；關閉／取代可能刪除舊副本。
- hide 暫時露出角色、保留 active content／content id，restore 恢復；兩者與 UI 按鈕同步並跨重啟保存。close 清除 active content，show-* 換成新內容並顯示。隱藏 HTML 會卸載，恢復重新載入；遊戲未存入 localStorage 的狀態不保留。工具不控制 HTML 音效開關、點擊、DOM 或主畫面設定。
- 編輯 HTML 後，用相同 content id reload，它只支援 HTML、保留隱藏狀態；隱藏時要試玩再 restore。有內容仍在討論就保持；要求暫時回角色畫面時 hide，明確關閉或內容過期／敏感時 close。有 id 時優先指定，避免舊動作更動新白板。
- shown、reloaded、hidden、restored、closed 表示 manager 成功接受對應操作，UI 仍可能顯示 renderer 錯誤；不宣稱實際畫面／音效已驗證。blocked、error 或 needs_clarification 時先讀原因，自行修正工具輸入錯誤；需求不足才問家人，不朗讀 JSON。
- HTML 音效於使用者首次操作解鎖，assistant 說話時 app 會降音量；header 可靜音。不從未驗證結果承諾音效已正常。

## 製作與維護作品

- 正式遊戲交付一份 `apps/<name>/index.html`，內嵌 CSS、JS 與小素材；不依賴 CDN、remote API、install、build、ES module import 或本機絕對路徑。只有需求明確需原生能力才做獨立 GUI。
- 從一開始同時支援桌面白板與手機：viewport、responsive／Canvas、resize、直橫向、Pointer Events、觸控控制、safe-area、約 44 CSS px 以上按鈕；不依賴 hover、鍵盤、固定解析度、fullscreen 或 Edge 專有 API。
- 交付前確認窄版手機與桌面無溢出、文字可讀、純觸控可完成、音效可解鎖、存檔可重載。用 `localStorage` 保存遊戲進度，但不承諾永久保證。
- 每個 app 有自己的資料與 README；不直接讀家庭記憶、logs、private config。玩法與作者在 `GAMES.md` 索引；完整操控放 app README，驗證過程放月份 archive，不在工具清單追加玩法流水。
- 臨時分析與實驗放 `scratch/`，穩定工具放 `tools/`；新增工具先驗證並記入口、授權、失敗處理，再更新本檔。
