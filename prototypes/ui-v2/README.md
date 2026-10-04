# 愛管家 UI v2 — CustomTkinter 原生預覽

正式 UI 的候選實作，尚未接回正式入口；請 review 後再批准整合。

## 開啟

- **open-demo.bat**：開啟預覽，依要求暫時顯示底部 Markdown／圖片／HTML 等驗收按鈕。
- **review-demo.bat**：同一畫面，加上底部驗收工具與示範對話。

臨時工具受 `--review-tools` 控制；不帶此參數啟動 `native/main.py` 即為乾淨畫面，正式整合不加入工具列。

HTML 每日用量會跨重啟保留。Review 列常駐顯示剩餘時間；當日額度耗盡時，HTML 按鈕停用並標示「今日已用完」。驗收時可按「重設額度」再按 HTML，這個重設工具不加入正式版。

使用現有 `ai_voice_assistant/venv/`，無須新增依賴。第一步按「下一步」會先完成模型查詢，成功後才進入第二步；也可手動按「更新並查詢模型」，檢查／選擇模型後再前進。查詢目前回傳明確標示的 demo 結果。若直接跳到最後啟動但尚未查詢，會回第一步，接著按「下一步」即可繼續，無須重開。主畫面沒有退出／切換全螢幕按鈕；F11、Esc 無法退出，**Alt+F4 關閉程式**。變更設定需重啟。

一般入口可輸入包含「白板」「圖片」「HTML」「遊戲」的訊息，開啟對應示範。這是模擬 adapter 的測試情境，非真實 AI 工具呼叫。

## 完成範圍

- 真正的 CustomTkinter 設定表單、主畫面、訊息佇列與圖示控制。
- 卡片式設定、即時摘要；統一柔和底色、深藍、字級、間距、細邊線與焦點狀態，移除重複裝飾標籤。啟動視窗依 monitor work area 置中，底部操作列保持可見。
- 設定選單為同視窗的圓角面板，對齊欄位寬度，標示目前選項；支援方向鍵／Enter／Escape、點擊外側收合與長清單捲動。模型選項循環使用最多 11 個 row，不一次建立整份大型 catalog 的 widgets。
- 直接使用原 AnimationController；背景、五種 state 動畫、幀序與時間不修改。
- 擴大白板；對話 19／21／24 px；mic、speaker、send 與白板控制使用圖示、hover 說明。
- 圖示使用一致的 24-unit grid、圓頭線條與高解析 artwork；mic／speaker 的開啟、靜音、固定文字鎖定狀態分別以底色與圖示區分，hover 說明不增加常駐文字。
- 主畫面以深藍頁首、霧藍工具列、暖米色對話與鼠尾草綠圖示點綴；裝飾限於細線／色塊，不增加文字。白板隱藏後的恢復圖示固定於舞台左下角，與邊緣保留間距。
- 四種輸入／輸出組合，manual／auto mute、打斷、FIFO、逐筆取消與舊回合 callback 隔離。
- 沿用 Windows keyboard guard、GlobalInputMonitor；依設定於 idle 詢問鍵鼠操作的使用者。
- 真實 Edge HTML 白板、Markdown renderer、圖片與每日額度；HTML 到期關閉，md／image 可繼續使用。
- Markdown 使用單一捲動元件填滿白板；隱藏／展開保留閱讀位置。白板顯示期間暫停操作詢問，隱藏／關閉後依收音狀態恢復。
- Markdown 與文字輸入框均於內容超出高度時自動顯示可拖曳的垂直捲軸，內容縮短後自動隱藏；輸入框捲軸使用與背景不同的顏色。
- Edge 保留隔離 App profile，依實際網頁 render HWND 裁切標題列與瀏覽器 UI；內容跟隨白板尺寸，視窗嵌入走 UI 執行緒。
- 隱藏 HTML 時真正停止其 process。Demo 遊戲以隔離 localStorage 保存題目，恢復時重載。

CLI 更新／query、AI、收音與 TTS 仍使用 `DemoCatalog`／`DemoTurnService`；正式服務接入留到畫面與行為批准之後。

## Review 程式碼

| 檔案 | 責任 |
| --- | --- |
| native/main.py | 啟動、單一實例、smoke test、退出清理 |
| native/startup.py | 草稿表單、階層選單、背景 query、SessionConfig |
| native/main_window.py | 候選版面、回合事件、白板、guard／activity 接點 |
| native/fullscreen_host.py | Windows monitor 實際邊界與全螢幕校正，不使用 DPI 虛擬尺寸 |
| native/widgets.py | 色彩、字體、卡片、圖示、tooltip、可捲動與循環繪製的設定選單 |
| native/domain.py | 不依賴 UI 的 session policy、queue、每日額度 |
| native/services.py | Catalog／TurnService Protocol 與可替換的模擬 adapter |
| native/html_host.py、windows_job.py | Edge 嵌入、限定 HTTP root、Job Object 程序清理 |
| native/validation.py | 草稿型別／範圍驗證與 session snapshot |
| native/test_*.py | 69 項 domain、故障、原生 UI、Windows／HTTP 測試 |

重用原 UI class 的 Windows helpers，但不執行原 UI 建構流程。這是隔離預覽的過渡接法；批准後抽為共用元件，避免長期繼承整個舊 UI。

## 驗收路線

1. 語音輸入／輸出啟動，在 Review 列按「朗讀」，送出兩筆文字，試排隊、取消、打斷送出。
2. 朗讀期間按 mic，確認打斷與收音；demo 5 秒未收音後恢復 queue。
3. 關 speaker，確認只停止聲音，文字與訊息順序仍保留。
4. 切換五種 state 查看原動畫；選 AUTO 回正常驅動。
5. HTML 作答，隱藏／展開確認進度；按「剩 10 秒」驗證到期，再開 md／image。
6. Alt+F4 重開，選固定文字，確認 mic／speaker 的鎖定圖示與行為。

文字以送出按鈕或 Ctrl+Enter 送出，普通 Enter 保留換行／IME 確認。

## 已驗證與限制

```powershell
.\ai_voice_assistant\venv\Scripts\python.exe -B -m unittest discover -s prototypes/ui-v2/native -p 'test_*.py' -v
.\ai_voice_assistant\venv\Scripts\python.exe -B prototypes/ui-v2/native/main.py --smoke-html --smoke-fullscreen --review-tools
```

完整修正、風險與驗證紀錄見 [AUDIT.md](AUDIT.md)。候選版 67 tests 通過，含跳步恢復、白板 viewport／活動暫停／閱讀位置／音訊狀態、UI thread attach、視窗 ownership 重新驗證、resize 等待期限，以及跨重啟耗盡額度的提示／demo 重設。新增驗證 startup work area、選單鍵盤選擇／模型失效、500 個模型的最後一項可見與可選、popup dismiss／disable／destroy 後既有 root bindings 保留。另實測既有 runtime 的耗盡額度，經 Review 重設與 HTML 按鈕 callback 成功嵌入真實 Edge。原元件前輪 170 tests 通過。Native smoke 覆蓋五頁設定、全螢幕視窗／client 邊界、真實 keyboard／screen guards、主畫面、回合打斷、Edge 嵌入、隱藏、恢復、resize、到期封鎖與 md fallback；測試使用暫存 runtime。

本輪重現並修正 125% 系統 DPI 下，1920×1200 螢幕只展開到 1536×960 的問題；原生視窗與 client 現皆吻合 monitor。另測試 app window scaling 1／1.25／1.5／2 及原生 resize 後校正，並修正啟動選單殘留 scaling callback。實際檢查 Markdown／HTML 主畫面，Markdown 1308×915、HTML 1308×862 均吻合各自容器；HTML 遊戲作答後隱藏／展開，題目與完成題數保留，操作期間沒有新增 presence 詢問。HTML 取得焦點時 F11、Esc 仍維持全螢幕，Alt+F4 關閉 QA 視窗正常。這不等於實際切換 OS DPI／多螢幕或全部快捷鍵驗收，商用品質仍需完整實機 review。

未接真實 CLI／音訊。家長 PIN、跨帳號額度、正式 WTS／power 通知與任意 HTML 記憶體狀態恢復尚待整合。已加入 desktop 可用狀態的 polling gate，但未實際鎖機驗收。設定目前是記憶體草稿；demo 用量、HTML profile 與錯誤 diagnostic 存於 gitignored `native/.runtime/`，不具防篡改能力。

沒有修改正式入口、原 Python UI、assets、private config／workspace 或正式 logs。`legacy-web/` 只留歷史說明；舊程式碼與素材已移除。
