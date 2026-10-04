# UI v2 規畫與 Native Review Guide

更新：2026-10-04。原生候選實作，等待使用者批准；未整合正式 UI。

## 已確認的方向

1. 沿用 CustomTkinter；HTML 草稿停用。原生 demo 就是預計交付版面的候選程式碼。
2. 初始設定不全螢幕，啟動後全螢幕。主畫面沒有退出、設定或切換全螢幕入口，**Alt+F4 關閉**，保留鍵盤封鎖與鍵鼠活動詢問。
3. 去除口號、裝飾文案。以分組、間距、圖示與必要狀態呈現，hover 解釋動作／鎖定原因。
4. 原背景、人物、全部 state 動畫、幀序與時間沿用，不修改素材。
5. 原生畫面須達到正式候選版的視覺完成度，不能以預設元件布局當交付標準。
6. 使用者明確批准前，不修改正式入口。工作限於 prototypes/ui-v2/。

## 視覺與布局

延續原專案深藍與暖色場景，以中性淺灰、白色面板、細邊線分層。

啟動視窗採左側步驟、中央卡片、右側即時摘要、固定底部操作。主畫面以原舞台／白板為主，右側保障對話閱讀宽度；移除原大型狀態／操作區，提高白板有效高度。

對話預設 21 px，以角色標籤、低飽和氣泡與柔和捲軸區分。閱讀舊訊息不強制捲到底。输入與 mic／speaker／send 收進同一個 composer；queue 顯示在上方。焦點邊線、hover、鎖定圖示都由共用 widgets 定義。

一般入口不帶驗收控制項；Review 入口多出測試列與範例對話，兩者共用候選 UI。原 artwork 的尺寸適配沿用 AnimationController，不生成新場景或人物。

## 啟動設定

### AI 與更新

Backend → 安裝來源／版本 → 更新最新穩定版 → executable／auth 驗證 → query models／efforts → 選擇。

正式接入要各 backend Catalog adapter，不能假設五種 CLI 的命令相同或都是 npm。Codex 現有 client 有 model/list；其他 CLI 的 capability、pagination、effort 需逐一實測。

Native 使用 Catalog Protocol + DemoCatalog 回傳 ModelInfo，僅使用明確標示的虛構 IDs。換 backend 清空選擇；query 失敗不可啟動。正式版仍需補更新失敗 fallback、不支援列舉時明確使用 CLI 預設的 UX，不以硬編碼正式模型代替查詢。

### 輸入與輸出

能力獨立：語音 + 文字／固定文字，四種組合。固定文字輸入不開錄音，固定文字輸出不預熱 TTS。正式 adapter 補裝置枚舉、測試錄音、試聽。

### 白板與時間

HTML 每日 30 分鐘，0–1440 可調；0 表示不開放。台灣時間每日 00:00 重置，跨重啟累計。隱藏、關閉不扣；md／image 不限。

### 進階設定

公開 config 全部葉節點按功能分類建立 typed 草稿表單，主要標籤為繁體中文。Model／effort 統一由第一步管理。全螢幕退出固定 Alt+F4，不提供 F11／Esc 選項。

分類涵蓋 audio、vad、whisper、wake_word、semantic_chunker、tts、pipeline、speaker recognition、presence、hot listen、LLM／工具權限、activity prompt、heartbeat、schedule、whiteboard、archive、UI。

Native 已加入 transactional 收集、型別、有限數值與候選消費欄位的安全限制；正式版仍需完整 SettingsSchema（範圍、依賴、單位、secrets、未知 key 保留）及 private overrides atomic save。草稿編輯不能直接呼叫 runtime setter。

### 啟動確認

摘要後建立 frozen SessionConfig，驗證服務、保存正式設定、初始化必要資源，再進全螢幕。正式版初始化失敗應回設定並保留草稿。Native 的額度初始化錯誤留在設定畫面，其餘非預期錯誤清理後關閉 demo 並留下 diagnostic；尚需正式 rollback UX。Native 只在本 process 使用設定，不保存至正式檔案；關閉重啟才能變更。

## 聲音與訊息

SessionConfig 固定能力；SessionController 管理 runtime mute、phase、queue、generation。

`mic_muted = fixed_text_input OR manual_mute OR speaking`

| 行為 | 規則 |
| --- | --- |
| TTS 開始 | auto mute，不覆寫 manual_mute |
| TTS 結束 | 恢復原先手動狀態 |
| 朗讀中按 mic | 取消回合／待播音訊，確認停止後開收音，queue 保留 |
| 固定文字下按音訊圖示 | 保持鎖定並解釋原因 |
| 關 speaker | 只停止播放，不取消生成中的文字；重開不重播舊段 |
| 忙碌送文字 | FIFO 排隊，不假裝 backend 已收到 |
| 打斷送出 | 取消當前回合、失效舊 generation、送最早一筆 |
| mic 打斷後未說話 | no-speech timeout 後恢復 queue，demo 使用 5 秒 |

正式回合在 generation done + TTS 完成 + playback drained 後才釋放。Demo 分開發 generation_done／playback_done；靜音不跳過文字生成。

每則最多 8,000 字、10 筆待送；超限保留草稿。可逐筆取消，前三筆直接顯示，其餘用同視窗 overlay 檢視。主畫面沒有返回設定的對話框。

正式 adapter 必須沿用 pipeline 仲裁，使用者 queue 優先於 heartbeat／非急迫排程。失敗不自動重送可能已接受的回合；以 generation／turn id 隔離取消後的 callback。

## 白板與額度

VISIBLE、HIDDEN、CLOSED 分開。HTML 的 show／reload／restore 都要檢查額度；正式 manager 與 tool 亦須檢查，不能只擋 UI。

HtmlBudget 使用 monotonic 計算持續時間，台灣日期分桶、午夜拆分、atomic file replace、重啟保留；時間倒退不補額度。HTML 真正 attach 且可見才計時。

隱藏停止 HTML process／keyboard bridge，確保背景不繼續玩。Demo 遊戲每次作答保存 localStorage，重開恢復題目。任意 HTML 的記憶體狀態仍需合作 pause/resume bridge 或 checkpoint+unload，不能用 hide window 冒充 pause。

到期關閉 HTML，禁止再開；md／image 不受影響。調整上限不清除已用量。正式 tool 回覆 html_daily_limit_reached、remaining_seconds 與替代格式。

Native 是同 demo runtime 單一 instance，已有 desktop 可用狀態 polling。跨 Windows 帳號共用、ACL、WTS／power 通知、異常關機與跨程序交易儲存留待整合；不可宣稱已有家長防護。

## 原生重用與技術邊界

- AnimationController：原幀、原合成規則、public config offset／interval。
- GlobalInputMonitor：沿用 widget／global 監看；demo 啟用 activity prompt，受 idle、voice capability、manual mute gate。
- Windows guard：沿用低階 hook、範圍判定、HTML 按鍵橋接與防休眠；Alt+F4 關閉，F11／Esc 阻擋。
- Markdown：沿用真正 WhiteboardMarkdownRenderer。
- HTML：NativeHtmlRenderer 繼承原 renderer，使用 suspended launch 與私有 Windows Job Object，驗證 job membership 與真正 parent HWND；HTTP 只提供 web_assets/。
- Native fullscreen 保持 window identity 且無標題列；沒有返回視窗化的 UI。
- 目前只重用 LegacyWindow helpers，不呼叫原建構流程；整合時抽為共用 guard／host 元件，不長期繼承整個舊 UI。

## 整合順序與驗收

1. 使用者 review 原生視覺與互動；未批准前不改正式入口。
2. 補 CLI Catalog adapters、update／auth error UX、音訊裝置與 SettingsSchema。
3. 解耦原文字／語音回覆路徑，接到共用 controller/service event，保留 cancellation／arbitration。
4. 額度權威放 manager/service；補 tool gate、跨帳號與鎖屏處理、HTML state policy。
5. 真實語音、Edge、DPI、多螢幕、快捷鍵與清理驗收，通過才替換正式入口。

必驗：五頁與 query errors、四能力組合、queue／cancel／stale callbacks、五種動畫、全螢幕、鍵鼠活動、白板生命週期與到期、重啟／午夜／倒退時鐘／損壞記錄／第二 instance；1920×1080、1366×768、100／125／150／200% DPI、中文 IME、長回覆。

完整紀錄見 [AUDIT.md](AUDIT.md)：已通過 43 候選 tests、170 原元件 tests；Native smoke 通過五頁、主畫面、打斷、Edge attach／hide／restore／expiry、HTML 封鎖及 md fallback。精修前實測 F11／Esc 保持全螢幕；audit 後實測 guard 安裝／卸載，尚未重做逐鍵驗收。畫面擷取工具出現 monitor capture error，最後一輪視覺與 DPI QA 尚待補，不能以功能 smoke 取代。

## 待決定

- 同機共用額度或帳號分開：建議同機共用。
- 初始設定／提高額度的家長 PIN：建議需要。
- 更新失敗明確沿用現有可用 CLI：建議允許，不靜默 fallback。

尚未收到回答，不視為批准；舊 Web 草稿不能覆蓋本文件的原生與 Alt+F4 要求。
