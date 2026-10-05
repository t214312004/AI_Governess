# 本機排程與報告

排程支援一次、每日與每週提醒或 LLM 摘要。正式 UI 右側對話標題旁的行事曆圖示可建立、
編輯、啟停、刪除排程及查看待領報告；Sophia 則透過 `tools/schedule_tool.py` 操作。

## 執行時機

`SchedulePoller` 獨立於 heartbeat，public default 開啟且每秒輪詢。只有程式開著、
`IDLE_LISTEN` 待機且沒有其他請求時才執行；使用者互動優先，未執行的時間依 miss policy 處理。
它不是 Windows Task Scheduler，不會自動開機或在程式關閉時通知。一般 heartbeat
public default 關閉，是另一個僅讀既有 context 的巡檢，不能執行排程或寫回記憶。

目前不開放 interval trigger，亦不開放到期控制網站、系統、相機、帳號、登入、付款或
外部工具；可用即時查詢資料來源產生摘要，但不能將「到時間執行任意腳本」視為排程能力。

## 建立與確認

以下在 `ai_voice_assistant/agent_workspace/` 執行；payload 存在 `tool_payloads/schedule/`。
建立輸入外層有 `draft`；展示身份 `PersonA` 應改成實際已確認的 requester：

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

```powershell
..\venv\Scripts\python.exe tools\schedule_tool.py draft-create --payload tool_payloads/schedule/reminder.json
..\venv\Scripts\python.exe tools\schedule_tool.py draft-confirm --draft-id <draft_id>
..\venv\Scripts\python.exe tools\schedule_tool.py draft-cancel --draft-id <draft_id>
..\venv\Scripts\python.exe tools\schedule_tool.py draft-update --draft-id <draft_id> --payload tool_payloads/schedule/change.json
..\venv\Scripts\python.exe tools\schedule_tool.py undo --operation-id <operation_id>
```

低風險自我提醒可直接得到 `created` 與預設 2 分鐘的 `undo_until`。其他情況可能得到
`needs_confirmation` 與 `draft_id`，等待確認後才用 `draft-confirm`；預設草稿 20 分鐘過期。
`needs_clarification` 要先檢查是否是 Sophia 的 payload 錯誤，只有缺少需求才問使用者。
授權依 Sophia 的 AGENTS／TOOLS 規則判斷，工具結果不提供身分驗證保證。

| Trigger | 必填時間欄位 |
| --- | --- |
| `once` | 未來的 ISO `run_at`，或 `date` + `time` |
| `daily` | `time`（24 小時制） |
| `weekly` | `time` + 非空 `weekdays`，Monday=0 至 Sunday=6 |

timezone 預設 `Asia/Taipei`。miss policy 支援 `skip`、`run_late`、`defer_until_idle`；
一次性預設 `run_late`，重複型預設 `defer_until_idle`。`edit` 用排程欄位 patch，
`draft-update` 可用欄位 patch 或外層 `draft`；巢狀 trigger／report 更新時提供完整該物件。
已被 claim 且執行中的排程不可編輯、刪除或啟停。

## 管理與報告邊界

```powershell
..\venv\Scripts\python.exe tools\schedule_tool.py list
..\venv\Scripts\python.exe tools\schedule_tool.py edit --schedule-id <schedule_id> --payload tool_payloads/schedule/change.json
..\venv\Scripts\python.exe tools\schedule_tool.py enable --schedule-id <schedule_id>
..\venv\Scripts\python.exe tools\schedule_tool.py disable --schedule-id <schedule_id>
..\venv\Scripts\python.exe tools\schedule_tool.py delete --schedule-id <schedule_id>
..\venv\Scripts\python.exe tools\schedule_tool.py reports-list --recipient <recipient>
```

報告設定是 `report.required: true`、`recipient`、必要的 `sensitive`；
`keep_latest_report_only: true` 只保留最新一期待交付報告，預設 false。
`reports-list` 只列 availability，正文由 app 依收件人與交付流程注入，成功交付後才標記
delivered。`reports-list --include-body` 與 `report-deliver` 保留為相容入口但回傳 `blocked`。

持久化資料在 Git ignored 的 `schedule_state/`，由 `ScheduleManager` 唯一寫入。
不要直接修改 schedule、draft、run、report JSON；payload 是暫時工具輸入，不是正式 state。
成功狀態包含 `created`、`updated`、`deleted`、`enabled`、`disabled`、`cancelled`；
使用 `message_for_user`／confirmation／clarification 欄位說明，不朗讀 raw JSON。
