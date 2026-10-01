# HTML 互動白板

HTML 互動白板讓愛管家直接在全螢幕角色舞台內開啟本機網頁 app。它適合小遊戲、
互動教材、模擬器與不需要網路的視覺工具；使用者可以繼續和愛管家說話，不必退出
全螢幕或切換到外部瀏覽器。

## 系統需求

- Windows 10 或 Windows 11
- Microsoft Edge（Windows 一般會預先安裝）
- 已依主 README 完成 AI Governess 安裝
- `whiteboard.enabled` 保持為 `true`

這項功能直接使用 Microsoft Edge 的 app mode 與 Windows child-window API，不需要
額外安裝 Python webview package。程式啟動時若找不到 `msedge.exe`，白板會顯示可讀的
錯誤訊息。

## 立即試用公開示範

Fresh clone 第一次啟動時，`agent_workspace_template/apps/` 會複製到本機 private
`agent_workspace/apps/`。公開版包含：

```text
ai_voice_assistant/agent_workspace/apps/html_whiteboard_demo/index.html
```

對愛管家說：

> 在白板打開 HTML 互動示範。

示範 app 可用方向鍵、WASD 或畫面按鈕移動圓球並收集星星，涵蓋 Canvas、動畫、
鍵盤、pointer/touch、Web Audio 與 `localStorage`。最高紀錄在關閉或重新開啟後仍會
保留。

## 與愛管家一起製作 app

可以直接提出完整需求，例如：

> 請在 `apps/math_game/` 做一個心算遊戲，完成後在白板打開讓我玩。

愛管家應將檔案放在自己的 app 資料夾，並使用 HTML whiteboard 開啟：

```text
agent_workspace/
  apps/
    math_game/
      index.html
```

新遊戲的正式成品應是單一、自包含的 `index.html`。CSS 與 JavaScript 直接內嵌，必要的
小型圖片與音效使用 inline SVG、data URL 或程式產生；不要依賴 CDN、remote API、外部
套件、build step、ES module import 或本機絕對路徑。這能讓同一份檔案直接在愛管家白板
與一般手機瀏覽器上使用。

### 桌面與手機相容標準

- 加入 `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`。
- 使用 responsive CSS 或依容器尺寸縮放 Canvas；監聽 resize／orientation change，避免固定
  1920×1080 排版。
- 使用 Pointer Events，並提供畫面上的觸控控制。鍵盤快捷鍵可以保留，但不能是唯一操作方式。
- 主要按鈕與控制區至少約 44 CSS px，使用 `env(safe-area-inset-*)` 避開瀏海與手機手勢區。
- 不依賴 hover、fullscreen、Edge 專屬 API 或桌面滑鼠；直向與橫向都要保持文字可讀、內容
  不溢出且能完成全部玩法。
- Web Audio 必須在第一次 click／pointer／touch 後才啟動；紀錄與設定只存 `localStorage`。
- 完成前至少以一般桌面尺寸與窄版手機尺寸檢查，並實際走完 touch-only 操作流程。

遊玩後可以繼續用語音要求修改：

> 題目速度慢一點，答對時多一個動畫。

愛管家修改完原始檔後會重新載入目前白板。重新載入會重開本局；使用
`localStorage` 保存的資料則會保留。白板頂端也有「重新載入」、「音效開啟／關閉」
與「關閉」按鈕。

## 支援能力

| 能力 | 支援狀態 |
|---|---|
| HTML、CSS、DOM | 支援 |
| JavaScript、ES modules | renderer 支援；跨平台單檔遊戲應使用 inline classic script |
| Canvas 2D、WebGL | 由安裝的 Edge 與顯示卡能力決定 |
| `requestAnimationFrame`、timer | 支援 |
| 鍵盤、滑鼠、pointer、touch | 支援；方向鍵、空白與 WASD 另有跨 process 輸入橋接 |
| Web Audio、`audio`、`video` | 支援本機素材；首次播放仍需使用者輸入事件 |
| `localStorage` | 支援並保存在本機 `whiteboard_state/html_profile/` |
| 相對路徑素材 | renderer 支援；跨平台單檔遊戲應將小型素材內嵌 |
| 外部網站、CDN、remote API | 不支援；HTML app 的網路存取預設封鎖 |
| Python／主程式 bridge | 不提供；HTML app 不會直接呼叫 Python API |

入口檔案必須是 UTF-8 `.html` 或 `.htm`，大小上限預設為 5 MiB。CSS、JavaScript、
圖片、音效等資源必須放在入口檔案所在資料夾或子資料夾。

## 說話時自動降低遊戲音量

HTML 白板會在每份頁面最早期注入本機 audio bridge。當愛管家進入 `SPEAKING`
狀態時，Web Audio 與 HTML media 音量會平滑降至設定值；說話結束後恢復，鍵盤焦點
也會交還給遊戲。

預設音量是 20%：

```json
{
  "whiteboard": {
    "html_audio_duck_volume": 0.2
  }
}
```

在 `config.local.json` 將值設為 `0.0` 可在愛管家說話時完全靜音，設為 `1.0` 則不
降低。有效範圍為 `0.0` 到 `1.0`。白板頂端的音效按鈕是使用者手動靜音，優先於
自動音量降低。

## Whiteboard CLI

通常由愛管家自行呼叫；開發或除錯時可從 `ai_voice_assistant/agent_workspace/` 執行。

先建立 payload：

```json
{
  "title": "HTML 白板示範",
  "html_path": "apps/html_whiteboard_demo/index.html"
}
```

將它存成 `tool_payloads/whiteboard/open_demo.json`，然後執行：

```powershell
..\venv\Scripts\python.exe tools\whiteboard_tool.py show-html --payload tool_payloads/whiteboard/open_demo.json
..\venv\Scripts\python.exe tools\whiteboard_tool.py status
..\venv\Scripts\python.exe tools\whiteboard_tool.py reload --content-id <content_id>
..\venv\Scripts\python.exe tools\whiteboard_tool.py get-content --content-id <content_id>
..\venv\Scripts\python.exe tools\whiteboard_tool.py close --content-id <content_id>
```

`content_id` 可避免延遲的 reload 或 close 誤操作較新的白板。

## 安全與資料邊界

- `WhiteboardManager` 只接受 `agent_workspace/apps/` 底下的 HTML 入口。
- 本機 HTTP server 只監聽 `127.0.0.1`，並只提供入口檔案所在資料夾。
- 路徑解析後若離開 app 根目錄會回傳 `403`。
- Content Security Policy 與 Edge host resolver 會封鎖 remote script、fetch、frame、
  form submission 與外部 hostname。
- HTML app 沒有呼叫 Python 或讀取其他 private workspace 檔案的 bridge。
- app 原始碼、最高紀錄、Edge profile 與 active whiteboard state 都是本機 runtime
  data；`agent_workspace/` 和 `whiteboard_state/` 預設不提交 Git。

HTML app 仍是可執行程式碼。只執行自己建立或已檢查過的 app；若要把某款 app 放進
公開 template，先確認內容不含 API key、家庭資料、第三方未授權素材或 remote tracker。

## 疑難排解

**白板顯示找不到 Microsoft Edge**

確認下列任一路徑存在，或重新安裝目前支援的 Microsoft Edge：

```text
C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
C:\Program Files\Microsoft\Edge\Application\msedge.exe
%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe
```

**修改後仍看到舊畫面**

按白板的「重新載入」，或請愛管家重新載入目前 HTML 白板。不要直接修改
`whiteboard_state/`。

**方向鍵沒有控制遊戲**

系統會在白板開啟、重新載入以及愛管家說完話後，自動將鍵盤輸入交給遊戲。若曾切換到
其他 app，可點一下遊戲畫面取回焦點。內嵌 Edge 因 Windows child-window 焦點限制而沒有
收到 native keyboard event 時，localhost input bridge 會轉送方向鍵、空白鍵與 WASD；
bridge 使用有序 event queue 保留快速點按、`keydown` / `keyup` 與按住時的 `repeat`，
事件會從目前 focused element 往 `document`、`window` bubble。遊戲不應拒絕
`isTrusted === false` 的 keyboard event。

**沒有聲音**

Web Audio 通常需要第一次鍵盤、滑鼠或觸控操作才能開始。也請確認白板頂端顯示
「音效開啟」。

**想重設最高紀錄或 web storage**

完全關閉 AI Governess 與其 HTML 白板後，刪除本機
`ai_voice_assistant/whiteboard_state/html_profile/`。這會清除所有 HTML app 的 Edge
profile 與 `localStorage`。

## 開發驗證

修改 HTML whiteboard 核心程式後，請執行：

```powershell
cd ai_voice_assistant
.\venv\Scripts\python.exe -m pytest -q tests/test_html_whiteboard.py tests/test_whiteboard_manager.py tests/test_whiteboard_tool.py tests/test_main_window.py
```

發佈前再執行完整 `pytest -q` 與 repository root 的 `scripts/pre_git_audit.ps1`。
