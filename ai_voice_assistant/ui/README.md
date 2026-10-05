# 使用者介面層（UI）

## 正式啟動流程

`main.py` → `StartupWindow.prepare()` → 真實 `VoiceAssistant.prepare_for_gui()` → `session_window.VoiceAssistantUI.run()`。

- `startup.py`：五步設定，使用 layered config 的完整副本；backend、model、effort、語音模式、額度與字級有專用控制，其餘設定依分類編輯。未知本機設定也保留。
- `startup_window.py`：非全螢幕視窗與背景準備工作；Tk 操作僅在主執行緒執行。設定原子寫入 private config，啟動失敗會回復設定並可重試。
- `llm/model_catalog.py`：向已安裝 CLI 查詢模型與能力，支援更新、取消、逾時與子程序清理。模型識別字沒有寫死在正式 UI。
- `theme.py`：初始設定與主畫面共用色票，以 Sophia 原有背景的暖白、木質棕、香檳金和人物服裝的霧藍色搭配。
- `session_layout.py`、`session_theme.py`：主畫面版面與視覺元件；初始設定沿用相同的品牌圖示與配色風格。
- `components.py`：共用向量圖示、選單與控制元件。
- `session_window.py`：正式 UI，呼叫原有 `main_window.py` constructor，保留真實 callbacks、白板輪詢、排程、對話歷史及生命週期。

## 主畫面

- 初始設定按「啟動」後進入全螢幕。`fullscreen_host.py` 用 Windows monitor bounds 校正 DPI 尺寸。只接受 Alt+F4 退出；F11、Esc 與原有系統快捷鍵防護持續生效。
- 舞台使用原有背景與所有角色動畫。右側對話字級由初始設定決定，長對話與多行文字輸入都有捲動列。
- 麥克風與播音各有獨立圖示。播放期間麥克風顯示自動 mute；語音輸入模式下按 unmute 會打斷並收音。固定文字模式無法解除相對應圖示的停用。
- 打字與送出在忙碌期間仍可使用；待送訊息 FIFO 最多 10 則、每則最多 8,000 字，可取消或「打斷並送出」。待送清單限制高度並可捲動。
- 主畫面不提供 backend、model、effort、STT、TTS 設定切換。排程管理沿用原有功能。

## 白板

- Markdown、圖片與 HTML 使用原有 manager／工具協定。顯示白板時暫停使用者活動提示，隱藏或關閉後恢復。
- 關閉程式不清除白板內容；重開會恢復原本的 Markdown、圖片或 HTML。明確按白板關閉才移除 active state；HTML 仍受當日剩餘額度限制。
- `markdown_host.py` 管理 Markdown 的 callback 與 timer；內容填滿白板並支援捲動。
- `embedded_html.py` 沿用既有 HTML server、audio／input bridges 與 CSP；用實際 render HWND 裁切 Edge chrome，沒有內層縮小、放大或關閉控制。`windows_job.py` 只管理本次啟動的 browser process tree。
- 隱藏後的恢復圖示固定於舞台左下角。HTML 隱藏時卸載 renderer，重新顯示會載入原頁面；固定 localhost origin／profile 保留 localStorage。頁面未自行保存的記憶體狀態不會保留。
- `core/html_usage.py` 保存每日 HTML 用量，預設 30 分鐘、Taipei 每日 00:00 換日。只對實際附著且可見的 HTML 計時；隱藏、關閉、鎖定桌面與系統睡眠不計時。用完關閉 HTML，Markdown／圖片不限時。manager 與工具端讀取同一份額度紀錄。
- 紀錄寫入失敗或損壞時停用 HTML，避免額度被繞過。關閉 UI 前先結算額度，再停止 renderer、輸入監看與 Windows guards。

## `animation_controller.py`

- 從 `assets/states/` 載入狀態動畫檔或 numbered PNG frames，並支援從 `assets/states/layers/` 合成共用背景與各狀態 foreground frames
- 各狀態 frame 數量可不同，依檔名數字排序
- 若圖片不存在，會退回純文字狀態顯示
- 支援依舞台大小重算圖片尺寸
- 只保留最近兩種尺寸的圖片快取，避免頻繁 resize 時記憶體持續上升

## `global_input_monitor.py`

- 預設會優先使用目前視窗的鍵盤/滑鼠綁定來監聽前景互動；無法使用時才退回 `pynput`
- 鍵盤按鍵或滑鼠超過門檻位移時，會呼叫 `assistant.on_user_activity()`
- 啟用狀態、滑鼠位移門檻與是否要求前景使用本次啟動選定的設定
- 這個提示流程只會在語音模式且 `IDLE_LISTEN` 狀態下啟動

## `html_whiteboard.py`

- 啟動僅監聽 `127.0.0.1` 的 app server，並拒絕離開 HTML 入口資料夾的路徑
- 將 Microsoft Edge app-mode window 改成 CustomTkinter 白板 Frame 的 Windows child window
- 透過 CSP 與 Edge host resolver 限制 HTML app 的外部網路存取
- 在 app script 執行前注入 audio bridge，支援自動 ducking 與手動靜音
- 透過 localhost input bridge 轉送方向鍵、空白與 WASD，避開跨 process child-window 的焦點限制
- 使用固定、Git ignored 的 `whiteboard_state/html_profile/` 保存 `localStorage`

## 驗證

一般回歸測試：`venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider`。

原生 UI／Edge 測試須在可互動的 Windows desktop 單獨執行：先設定 `$env:AI_GOVERNESS_NATIVE_TESTS='1'`，再執行 `venv\Scripts\python.exe -B -m pytest -q -s -p no:cacheprovider tests/test_native_session.py`。測試使用暫存設定與 workspace，`-s` 避免 Windows Tcl 與 pytest fd capture 影響後續 Tk root 的建立。
