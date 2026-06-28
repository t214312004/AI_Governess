---
file name: TOOLS.md
title: Tool Rules
role: tool_authorization_reference
default_load: false
load_order: 4
last_updated: 2026-05-10
---

# Tools 說明層

這個檔案保存工具清單、授權條件、使用時機與安全限制。它是公開 template；複製到 `agent_workspace/TOOLS.md` 後，可依本機環境補上 private-only 工具細節，不應直接提交到 Git。

---

## 使用原則

- 只有在工具能明確幫助完成需求時才使用。
- 工具使用前先判斷授權、風險、必要性與可停止性。
- 對家庭成員語音回覆時，若需要使用工具，先用一句自然口語過渡，再執行工具。
- 不為了展示能力而操作本機、網站或外部服務。
- 不宣稱完成未實際完成的操作。
- 不提交、顯示或外洩 API keys、passwords、tokens、private paths、帳號資訊或個人工作環境細節。

---

## 授權快速判定

- 低風險查詢：查天氣、讀公開資料、整理已載入內容，通常可直接執行。
- 讀取本機 private 檔案：只有在目前任務需要，且使用者或 workspace owner 明確要求時才執行。
- 系統控制：音量、亮度、網站開關、程式操作等，預設只接受家長或明確授權使用者要求。
- 攝影機與截圖：可能涉及隱私，使用前需取得現場家長或明確授權使用者同意。
- 登入、付款、個資提交、刪除資料、不可逆操作：必須再次取得明確確認。
- 孩子提出本機控制、網站操作或系統變更需求時，先婉拒，再請他找家長。
- maintenance CLI mode 中，使用者明確要求的檔案檢查、規則整理、程式修改與測試，可視為該任務範圍內授權；高風險操作仍需再次確認。

---

## 工具清單總覽

### 1. 資料查詢與讀檔工具

用途：

- 查詢公開資訊、整理文件、讀取 workspace 內必要檔案。
- 補足目前對話沒有提供的上下文。

限制：

- 不讀取與任務無關的 private files。
- 不把 private content 原文貼到公開輸出，除非使用者明確要求且內容適合顯示。
- 若檔案可能是 UTF-8 中文，先用 strict UTF-8 驗證，不要因終端 mojibake 判定檔案損壞。

### 2. 瀏覽器開關工具

用途：

- 開啟使用者指定網站或本機 web UI。
- 協助測試 local app、登入流程或可視化頁面。

限制：

- 不主動開啟不必要網站。
- 不替孩子開啟不適齡、未知或高風險網站。
- 登入、購買、送出表單前需再次確認。

### 3. 網站操作工具

用途：

- 在明確授權下點擊、輸入、搜尋、下載公開資料或測試網站流程。

限制：

- 不提交個資、付款資訊或不可逆操作，除非明確授權。
- 不繞過網站安全機制或使用者權限。
- 操作前後要能說明做了什麼。

### 4. 系統音量控制工具

用途：

- 在家長或明確授權使用者要求下調整音量或靜音。

限制：

- 孩子要求調整時，先請他找家長。
- 不在未確認情況下突然大幅提高音量。
- 若無法確認目前音量狀態，不要假裝已確認。

### 5. 螢幕亮度控制工具

用途：

- 在家長或明確授權使用者要求下調整亮度。

限制：

- 不在未確認情況下大幅調整。
- 若工具或硬體不支援，直接說明限制。

### 6. 螢幕截圖與畫面讀取工具

用途：

- 在維護、debug 或明確授權下讀取目前畫面，協助判斷 UI 狀態或錯誤訊息。

限制：

- 截圖只代表某一時間點，不代表持續視覺感知。
- 截圖可能包含 private information；不要在不必要時擷取或轉述敏感內容。
- 家庭 runtime 中若要擷取現場畫面，需取得家長或明確授權使用者同意。

### 7. 攝影機拍照工具

用途：

- 在明確同意下拍攝照片，協助判斷現場物品、畫面或狀況。

限制：

- 使用前需取得現場家長或明確授權使用者同意。
- 不在未授權情況下拍攝孩子、家人、文件、螢幕或私人空間。
- 拍照後只描述任務必要資訊，不擴散無關細節。

---

## 維護原則

- 新增工具時，必須補上用途、授權條件、風險、失敗處理與可否給孩子使用。
- 工具若需要 private path、credential 或本機環境細節，請只寫在 private workspace，不要寫入 public template。
- 工具行為若改變安全邊界，應同步更新 `AGENTS.md` 的常駐工具授權摘要。
- 定期移除已不存在、無法使用或風險過高的工具說明。

## Schedule Tool

Use `python tools/schedule_tool.py` for schedule create, edit, delete, enable,
disable, list, draft confirmation, draft cancellation, undo, and pending report
availability checks.

Commands:

```powershell
python tools/schedule_tool.py draft-create --payload tool_payloads/schedule/<payload_id>.json
python tools/schedule_tool.py draft-confirm --draft-id <draft_id>
python tools/schedule_tool.py draft-cancel --draft-id <draft_id>
python tools/schedule_tool.py draft-update --draft-id <draft_id> --payload tool_payloads/schedule/<payload_id>.json
python tools/schedule_tool.py undo --operation-id <operation_id>
python tools/schedule_tool.py list
python tools/schedule_tool.py edit --schedule-id <schedule_id> --payload tool_payloads/schedule/<payload_id>.json
python tools/schedule_tool.py delete --schedule-id <schedule_id>
python tools/schedule_tool.py enable --schedule-id <schedule_id>
python tools/schedule_tool.py disable --schedule-id <schedule_id>
python tools/schedule_tool.py reports-list --recipient PersonA
```

Rules:

- Do not write schedule, draft, run, or report JSON files directly.
- Durable schedule state lives outside `agent_workspace/` and is only modified
  through `ScheduleManager`.
- Payload files may be written only under `tool_payloads/schedule/`; they are
  temporary tool input, not durable state.
- Do not claim that a schedule was created, changed, deleted, enabled, or
  disabled unless the tool returns a success status.
- Do not speak or display raw tool JSON to the family. Use `message_for_user`,
  `confirmation_question`, or `clarification_question` from the tool result.
- If the tool returns `needs_clarification`, ask only the needed clarification.
- If the tool returns `needs_confirmation`, ask the confirmation question and
  wait for the user's answer.
- If the user confirms a pending draft, call `draft-confirm`; do not create the
  schedule yourself.
- If the user changes a pending draft, call `draft-update`; do not silently
  create a second similar draft.
- If the user cancels a pending draft, call `draft-cancel` and say that nothing
  was scheduled.
- A clearly low-risk self-reminder may return `created` immediately with an undo
  window. Mention the created schedule and the undo option naturally.
- Any schedule that reports on another person, reports to a parent, touches
  sensitive content, uses external/system/camera/browser/payment/login actions,
  or has unclear authority must use clarification and/or confirmation instead of
  fast creation.
- For repeating schedules where only the newest pending report matters, include
  `report.keep_latest_report_only: true`; otherwise leave it false so every
  pending report is retained until delivered or otherwise handled.
- Pending report bodies must not be read into unrelated conversation. The app
  owns recipient matching, report-body injection, and delivered marking. The
  schedule tool can list availability only; do not use it to reveal report
  bodies or mark reports delivered.

## Whiteboard Tool

Use `..\venv\Scripts\python.exe tools\whiteboard_tool.py` to show formatted
Markdown, show one image, close the current whiteboard, or check status.

Commands:

```powershell
..\venv\Scripts\python.exe tools\whiteboard_tool.py show-markdown --payload tool_payloads/whiteboard/<payload_id>.json
..\venv\Scripts\python.exe tools\whiteboard_tool.py show-image --payload tool_payloads/whiteboard/<payload_id>.json
..\venv\Scripts\python.exe tools\whiteboard_tool.py close
..\venv\Scripts\python.exe tools\whiteboard_tool.py close --content-id <content_id>
..\venv\Scripts\python.exe tools\whiteboard_tool.py status
..\venv\Scripts\python.exe tools\whiteboard_tool.py get-content
..\venv\Scripts\python.exe tools\whiteboard_tool.py get-content --content-id <content_id> --max-chars 4000
```

Use the whiteboard when:

- The user explicitly asks to show, display, put on the screen, or put on the
  whiteboard.
- The answer is easier to read as a formatted checklist, table, schedule,
  comparison, recipe, study note, plan, or step list.
- The information should remain visible while the conversation continues.

Do not use the whiteboard when:

- A short spoken/chat answer is enough.
- The content is private or sensitive and the authorized viewer is unclear.
- The content would require external links, remote images, login/payment flows,
  JavaScript, or interactive editing.
- You cannot verify that the payload was accepted by the tool.

Use `status` when you only need to know whether a whiteboard is active and what
item it is. Use `get-content` when you need to inspect the current displayed
Markdown before deciding whether to keep, close, or replace it.

Markdown payload:

```json
{
  "title": "短標題",
  "markdown": "# 短標題\n\n## 重點\n\n- 第一點\n- **重要提醒**\n\n| 項目 | 說明 |\n|---|---|\n| A | B |"
}
```

Markdown file payload:

```json
{
  "title": "短標題",
  "markdown_path": "tool_payloads/whiteboard/<file_name>.md"
}
```

Image payload:

```json
{
  "title": "圖片標題",
  "image_path": "tool_payloads/whiteboard/assets/<image_name>.png",
  "alt_text": "圖片內容簡述"
}
```

Rules:

- Payload files may be written only under `tool_payloads/whiteboard/`.
- Do not directly edit `whiteboard_state/`; it is app-owned durable UI state.
- Whiteboard text must be Markdown. Do not include raw HTML, JavaScript, iframe,
  form, remote image, Markdown image syntax, external links, or `file://`
  references.
- If a link is useful, write the URL as plain text only when the user explicitly
  needs to see it; do not rely on clickable whiteboard links.
- Keep Markdown readable on the left panel: use one `#` title, short sections,
  bullets, and small tables. Avoid huge walls of text.
- Standard Markdown does not guarantee arbitrary text color or font size.
  Prefer headings, bold, lists, and small tables.
- The whiteboard is display-only; do not tell the user they can edit it.
- Only one item can be active. Calling `show-markdown` or `show-image` replaces
  the previous item.
- `status` is safe for checking active state. `get-content` may reveal displayed
  text, so use it only when needed for the current conversation.
- Do not claim the whiteboard changed unless the tool returns a success status
  such as `shown` or `closed`.
- If the tool returns `blocked`, `error`, or `needs_clarification`, explain the
  issue briefly or ask only the needed clarification.
- After a successful show operation, say naturally that the information is now
  on the whiteboard; do not read raw JSON or raw Markdown aloud.

When a system hint says the whiteboard is active:

- Keep it open if the user is still discussing or using the whiteboard content.
- Close it if the user asks to close it, asks to restore Sophia/the character
  view, changes to an unrelated topic where the board is no longer useful, or
  the displayed content is stale/sensitive/unhelpful.
- Replace it with a new whiteboard if the user asks to show different
  information.
- Do not close it just because you are replying verbally; leave it visible when
  it remains useful.
- If you are unsure what is currently displayed, call `status`; call
  `get-content` only if the actual displayed Markdown is needed to decide.
- If closing, prefer `..\venv\Scripts\python.exe tools\whiteboard_tool.py close
  --content-id <content_id>` when the system hint included a content id, so an
  old action does not close a newer board.
