# 使用者介面層（UI）

## `main_window.py`

目前 GUI 使用 `customtkinter`，是整個專案的主視窗。

### 已實作內容

- 啟動後自動進入全螢幕
- fullscreen geometry 直接使用 Tk 回報的邏輯桌面尺寸，避免在 Windows 顯示縮放下被重複縮小
- `Esc` 可退出全螢幕，`F11` 可切換；`Alt+F4` 保留 Windows 標準關閉行為
- 左右版面依比例切分，權重為 74:26
- 左側是角色舞台、狀態卡、主要操作按鈕
- 右側是對話面板、文字輸入區與設定抽屜
- 右上頂欄除了模式切換與設定按鈕，也包含標題與副標
- 右下文字輸入提示列會同時顯示模式說明與目前狀態
- 助手回覆時會持續更新同一個 AI 氣泡內容，而不是每個 chunk 新增一個氣泡
- 忙碌中會停用文字送出與後端切換
- 左下主按鈕在語音模式下可直接開始手動收音；若正在回應，則會變成打斷入口
- 右側小字標籤有額外安全高度、最小寬度與 `wraplength` 重算，避免在 Windows DPI 縮放下被裁切
- 窄螢幕會保障右側輸入區最小寬度，頂欄改為上下排列，設定與排程 drawer 會自動擴展
- 視窗 resize 會 debounce 動畫尺寸更新，並直接調整既有 frame，避免重複讀檔造成 UI 卡頓
- 排程刪除前會要求確認；排程檔案操作失敗時會在 drawer 內顯示錯誤
- 關閉視窗時會先 `config.flush()`，避免最後一次設定變更遺失

### 設定抽屜目前包含

- LLM 後端切換
- 熱監聽開關
- Whisper 裝置切換
- TTS 語速滑桿
- 熱監聽秒數輸入
- VAD 靜音毫秒數滑桿

其中 `TTS 語速` 會同步寫入 `config.local.json`，並立即套用到 `EdgeTTSEngine`；`tts.volume` 目前仍無對應的 UI 控制。

## `animation_controller.py`

- 從 `assets/states/` 載入狀態動畫檔或 numbered PNG frames，並支援從 `assets/states/layers/` 合成共用背景與各狀態 foreground frames
- 各狀態 frame 數量可不同，依檔名數字排序
- 若圖片不存在，會退回純文字狀態顯示
- 支援依舞台大小重算圖片尺寸
- 只保留最近兩種尺寸的圖片快取，避免頻繁 resize 時記憶體持續上升

## `global_input_monitor.py`

- 預設會優先使用目前視窗的鍵盤/滑鼠綁定來監聽前景互動；無法使用時才退回 `pynput`
- 鍵盤按鍵或滑鼠超過門檻位移時，會呼叫 `assistant.on_user_activity()`
- 啟用狀態、滑鼠位移門檻與是否要求前景都會快取在 instance 上，UI 更新設定後再同步刷新
- 這個提示流程只會在語音模式且 `IDLE_LISTEN` 狀態下啟動
