# Antigravity ACP：能力差異、目前補強與反應時間

歷史比較：2026-10-24。實作狀態更新：2026-10-25，Asia/Taipei。**使用者已接受 Gemini-only；正式 backend 已切為官方 ACP，核心 synthetic E2E 18 steps 與獨立 MEMORY write-back／delta 6 steps 均通過。** 真實 camera／audio 與完整家庭 UAT 等限制仍保留，不能據此宣稱全功能絕無下降。

本文件分開說明 native server 差異、目前 app 已實作的補強與歷史 latency。舊 `AntigravityCLIClient`、PTY／print 呼叫、CLI cache 輪詢與 `pywinpty` 已移除；下文引用它們是記錄遷移前 baseline。

## 目前能力與驗收狀態

| 項目 | 已知差異／目前實作 | 尚待確認的範圍 |
| --- | --- | --- |
| 模型 | 官方個人訂閱 ACP 的 Gemini-only 已由使用者接受；Claude／GPT-OSS 不再是本次切換阻塞項 | UI 明確 normalization 舊 Gemini variant；不可用 model／effort 不 silent fallback |
| 帳號與額度 | 僅接受 `oauth-personal`＋`g1-pro-tier`，移除 child API／Cloud／routing credentials | 不是逐筆 quota ledger；不由 tier 或 token 數推算剩餘 baseline quota／AI credits |
| Workspace 外檔案 | 正式 `governess_filesystem` MCP 已通過跨 workspace 讀寫、host state 與圖片辨識 | Google native boundary 未消失；scope 外需明設 task directory |
| Session effort | 正式 refresh／owned restart-resume 已確認 model／effort／yolo；修正早期 low 恢復成 high 的問題 | 本輪 fixture 成功不能證明所有 session corruption／網路中斷情境 |
| 家庭記憶 | Private 文件只補缺檔；AGENTS／MEMORY 與 instruction `TOOLS.md` 透過 ACP context 載入；初次讀取、continuity、獨立 MEMORY write-back／delta 均通過 | 使用 synthetic 記憶；家庭真實 state 未被測試修改，完整家庭 UAT 仍需另驗 |
| 文字輸出 | 共用 ACP streaming、keepalive、permissions、取消；預設 `final_segment` | Raw first chunk 不直接等於開始朗讀，工具旁白不應進 TTS |
| Search／圖片／shell／MCP／多輪 | 歷史 probe 有相關證據；正式 MCP read／write／image、context、多輪、工具中取消與恢復均通過本輪驗證 | 正式與歷史證據分開；未實測工具仍不由 capability 宣告推定通過 |
| 白板／排程 | 正式 public wrappers 的回覆＋host receipt／state 通過；native embedded HTML hide／restore／expiry／Markdown 通過 | 不代表 camera／audio 整套家庭 UAT 或所有 UI 情境均已測完 |
| Browser／camera／skills／plugins／hooks／subagents／image generation | 依官方 server、安裝與授權提供，沒有新增其他模型計費路徑 | 未完整驗證者不列為已通過，也不能由 capability 宣告推定等價 |

跨目錄的正式 MCP 預設 scope 為 **workspace＋目前 Windows 使用者 home＋`APP_DIR`**。一般 Desktop／Downloads 位於 home 時可由這條路徑操作；若經 OneDrive 轉址或檔案在別處，需將實際 task directory 加入 `llm.antigravity_cli.filesystem_roots`。

Filesystem MCP 拒絕整個 volume root，例如 `C:\`／`D:\`；請設定既存的任務目錄，例如 `D:\Family\Homework`。設定陣列會取代預設 `~` 清單；要保留 home 時可用 `["~", "D:\\Family\\Homework"]`。Workspace 與 `APP_DIR` 仍由 app 加入，symlink／junction 解析後也要符合 roots。這些工具不取代既有任務授權、排程確認或 camera consent。

`yolo` 自動處理工具 permission，無法改變模型 entitlement 或解除 native workspace boundary。早期同帳號、同 session 的 default／yolo 均拒絕 Claude，這與目前僅准 personal Pro 的計費限制是不同層次。

## 正式 client 的準備時間

本輪測量使用正式 runtime `1.4.3` 與 production `AntigravityACPClient`，`await ensure_ready()` 的少量觀察值為 **16.985／17.122／18.414 秒**，約為先前所述的 **16–18 秒級**。測量包含 process startup、initialize、session/new、Pro tier 驗證與 session config；沒有送模型回合。初始 UI 已支援從官方 Registry 更新至當下最新 release；這些數據仍只代表上述實測版本。

這與下節早期 raw probe 的 initialize／session 數值是不同批次與測量邊界。OS cache、網路、官方 runtime 與工具 setup 都會影響時間，不能據此保證固定速度或固定改善比例。

正式 app 準備後保留長連線，多輪不必每次重啟 server。Catalog 使用 synthetic workspace，查完會關閉自己的 client；家庭 workspace 的正式 client 另行準備，所以首次查詢與正式啟動可能各有成本。目前不能宣稱 catalog 與主畫面已共用同一 process。

正式 E2E 中另保留 **146.875 秒**的 post-refresh seed 慢回合，後續 after-cancel 回合為 3.312 秒、owned restart-resume 為 15.003 秒、恢復後 continuity 為 4.900 秒。這些情境不同，不能合併成一般回覆 benchmark。

原始 observer 在 production client 的 session filter 前計數，146.875 秒回合中的 tool counts 可能包含其他 session 的事件，**不是乾淨的無工具 latency sample**。慢回合仍保留，不用觀察器的事件數推論模型工具效率；正式 ACP 不保證每輪更快。

## 歷史反應時間：測試方法

下列為 **2026-10-24 遷移前的 PTY／raw ACP 比較**；資料完整保留，不是新 production client 的重新 benchmark。

- 舊一般 CLI `1.4.6`，官方 ACP `1.4.3`，同一 Google AI Pro 帳號。
- CLI 使用當時愛管家的 `AntigravityCLIClient`，包含 ConPTY、每輪重啟、conversation resume 與輸出處理。
- ACP 使用長存 server，完成 initialize、Pro tier、session setup 與 yolo 後測量。
- 模型為 Gemini 3.8 Flash／low、Gemini 4 Argon／medium；CLI 使用 variant ID，ACP 使用 family＋thinking level。
- 各三輪、相同 user prompt、交替順序，要求 exact `BENCH_<輪次>_OK`；12 個短回覆均符合，不使用工具。
- 各自保留歷史，只有 synthetic AGENTS／MEMORY；兩個額外檔案存取測試不列入 latency。
- 測量輸入到文字回覆，**不包含 STT、TTS、audio playback 或 GUI 排隊**。
- Native harness、system prompt、token／cache 不完全相同；沒有獨立 telemetry 證明有效 thinking budget 相等，不能當純 transport benchmark 或品質等價證據。

## 歷史完整回覆時間

單位：秒。ACP 排除一次性的 server 啟動與 session setup，但保留 session 首輪。

| Model／effort | 舊 PTY 三輪 | 早期暖機 ACP 三輪 | PTY 中位數 | ACP 中位數 |
| --- | --- | --- | --- | --- |
| Gemini 3.8 Flash／low | 13.691／15.106／36.737 | 30.080／5.139／3.235 | 15.106 | 5.139 |
| Gemini 4 Argon／medium | 11.744／17.662／13.590 | 7.631／5.063／3.083 | 13.590 | 5.063 |

算術平均：Flash 為 CLI 21.845／ACP 12.818 秒；Argon 為 CLI 14.332／ACP 5.259 秒。只有各三輪，平均與中位數都易受單次變異影響。

ACP Flash 第一輪 30.080 秒比 CLI 第一輪 13.691 秒慢，CLI 也有 36.737 秒的慢回合；原因未定位。這組結果支持「長連線在本次短對話中有較快中位數」，**不保證每輪更快、固定倍數加速或較短語音總延遲**。

## 歷史啟動、首段文字與恢復

| 早期 raw probe 項目 | 歷史觀察值 | 測量意義 |
| --- | --- | --- |
| Spawn → initialize | 該輪 22.347 秒，先前約 21–26 秒 | 尚未完成首次 session；不同於正式 client 的完整 ensure_ready |
| 第一個 session/new | 5.264 秒 | 該輪合計約 27.6 秒，尚未送模型 prompt |
| 同 server 另一個 session/new | 3.948 秒 | Refresh 可省 process startup |
| 含 stdio MCP 的 session/new | 單次 41.981 秒 | 工具 setup 可能另有成本，不能套用一般回合時間 |
| Process 重啟後 resume | 單次 7.858 秒，另加 startup | 不等於一般多輪 latency |
| Session load | 單次 43.970 秒 | 不宜當作每輪操作 |

舊 PTY 收集整輪輸出才 yield，因此首段文字接近完整回覆時間。早期 ACP raw first chunk 中位數為 Flash 5.128 秒、Argon 4.835 秒；正式預設 `final_segment` 要等可確認的回合完成才交給 UI／TTS，不能把 raw first chunk 當成已測得的喇叭發聲時間。

## 正式 E2E 與 regression 結果

[正式 synthetic E2E record](antigravity_acp_implementation_validation_2026-10-24.json) 於 2026-10-25 完成 **18 steps，全部 passed**；它是 production client 的獨立驗證，不把前述歷史 checks 換名計入。

Record 另有 `memory_writeback_validation`：**獨立 MEMORY fixture 的 6 steps，全部 passed**。分開呈現「核心 18＋memory 6」，不宣稱是 24 個去重後的整體情境。

| 正式 client 情境 | 本輪結果 |
| --- | --- |
| Startup／personal Pro／yolo／environment | 通過；確認 `g1-pro-tier`、model／effort／yolo、owned Job 與無 child API keys |
| Scoped MCP／圖片／context／多輪 | 通過；包含外部檔案讀寫、host assertion、圖片辨識、memory color 與 continuity |
| 獨立 MEMORY write-back／delta | `edit_text_file` 恰 1 次；host exact bytes＝initial bytes 的 canary replacement，AGENTS 不變、CRLF 保留；同 session 下一輪 2.963 秒且無 tools，context block 確認只有 NEW、沒有 OLD |
| Public 白板／排程 wrappers | 通過 exact reply＋host receipt／state；Markdown／圖片／hide／restore／close、HTML path／quota guard、draft／confirm／delete／reminder／undo／report guard |
| 工具中取消／下一輪 | 30 秒 fixture 真正開始後，cancel 0.015 秒回 cancelled；至少 35 秒後無 completion marker，after-cancel 3.312 秒成功 |
| Refresh／owned restart-resume／cleanup | 通過；恢復同 session 15.003 秒、continuity 4.900 秒，model／effort／yolo 正確，owned processes／tasks 清理完成 |
| 官方 Registry 更新 → 模型查詢 | 真實流程 17.140 秒；已是 `1.4.3`，只查 Registry、不重複下載，取得 Gemini model／effort 清單；未送模型 prompt |
| 全套 regression | **1223 passed、31 skipped、3 warnings，33.34 秒**；含 Registry future-release／rollback／offline discovery 與串流取消 regressions |
| Native runtime UI | **45 passed，6.80 秒**；包含安裝／更新按鈕與受控版本保存 |
| Native startup／audio／credentials＋embedded 白板 | **72 passed，61.29 秒**；真實 embedded HTML hide／restore／expiry／Markdown 通過 |

MEMORY 最初一次 fixture 的 LF expected 與實際 CRLF 不符，保留於 attempts 記錄；這是測試預期修正，不算產品失敗或自動 side-effect replay。後續改以獨立新 fixture 的 initial bytes 精確 replacement 驗證通過。

Pytest subsets 有重疊，不能相加。真實 camera／audio 與 STT→LLM→TTS 整套家庭 UAT 尚未完成。Browser／skills／plugins／hooks／subagents 等未完整驗證的項目仍保留限制；**本輪驗證通過不等於全功能已完全對齊或絕無下降**。

安裝／登入、synthetic smoke 與 pytest 指令見[實作驗證指南](antigravity_acp_migration_plan_2026-10-24.md#6-可重跑的實作驗證)。Production smoke 使用正式 client，沒有第二套 JSON-RPC transport；`--smoke` 消耗少量訂閱額度。

歷史 raw record 保留於 [antigravity_acp_probe_2026-10-24.json](antigravity_acp_probe_2026-10-24.json)。舊 latency probe 已依 compact／clean 要求移除；需要重現舊 baseline 時，可從遷移前 Git revision 取得舊 production client，依上述方法重新量測。
