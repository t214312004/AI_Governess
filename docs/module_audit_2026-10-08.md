# Module audit — 2026-10-08

本輪檢查 `ai_voice_assistant/` 的 77 個正式 Python module，修復 9 項問題，並增加 22 個回歸測試案例。開始前 working tree 已有 logging 相關修改；本輪保留這些變更，沒有 commit 或 push。

## 方法與範圍

- 逐檔檢查模組責任、輸入處理、錯誤路徑與資源生命週期；大型 `core/assistant.py`、`ui/main_window.py` 集中檢查請求切換、取消、關閉、排程／白板整合與 UI callback。
- 對上述 77 個 module 進行 strict UTF-8 讀取及 AST parsing；使用 `pyflakes` 檢查主要程式、工具與修改過的測試。
- 先跑原有完整測試取得基準；可重現的缺陷補回歸測試，再修改實作並跑完整測試。
- `start.bat`、`debug.bat`、`setup_shared_venv.bat`、`scripts/download_models.ps1`、`scripts/pre_git_audit.ps1` 另做原始碼檢查，未執行重建環境或下載模型的操作。
- 排除 `scratch/` 的一次性腳本、private `agent_workspace/`、本機設定、模型、音檔、環境與產生檔案。未重寫私人 Markdown。

以下「未新增修補」表示在本輪檢查與自動測試範圍內，沒有確認新的可重現缺陷；不代表所有環境、所有執行路徑均已驗證。

## 已修復問題

| ID | Module | 觸發條件與原問題 | 修補與驗證 |
| --- | --- | --- | --- |
| A01 | `core/pipeline/output_processor.py` | 單次 token 很長，標點落在 `max_chars` 之後時，先掃描標點的邏輯會直接輸出過長 TTS chunk。 | 標點搜尋限制在 `max_chars` 範圍；2 個案例確認單次與跨 token 輸入均遵守上限。 |
| A02 | `core/audio_player.py` | callback 已複製 PCM 後才收到 interrupt 或 generation invalidation，該次 callback 仍可能輸出舊聲音。 | 交還 PortAudio 前重新檢查取消與 generation，清零失效 buffer；2 個案例在複製後插入取消／失效，驗證靜音與播放狀態。 |
| A03 | `llm/codex_cli_client.py` | `turn/started` 處理 deferred interrupt 時，在接收迴圈內等待 RPC 回覆，而回覆也需要同一個接收迴圈讀取，形成等待直到 timeout。 | 將 interrupt 排入受追蹤的獨立 task，關閉／啟動失敗時一併清理；以真實 `asyncio.StreamReader` 模擬 RPC 往返，確認接收迴圈持續工作並完成取消。 |
| A04 | `llm/claude_code_client.py` | 取消、關閉或請求完成只處理 CLI 根程序，工具子程序可能殘留。 | 改用既有 `create_owned_subprocess`／Windows Job；所有結束路徑釋放 owner，關閉可重複呼叫；新增 3 個資源清理案例。 |
| A05 | `llm/claude_code_client.py` | stdout 單行 JSON 超過 asyncio 預設約 64 KiB 時，stream 讀取失敗；大型 tool／assistant event 可觸發。 | 設定 16 MiB 的有界讀取限制，與既有其他 stdio backend 一致；實際啟動本機 Python 假 CLI，輸出 256 KiB JSON 後仍能讀到下一個 text delta。 |
| A06 | `tts/rate_limits.py` | `nan`、`inf`、`-inf`、溢位字串通過 `float()`，後續語速取整拋錯，造成 Edge TTS 初始化／設定失敗。 | 非有限值回到 `+0%`；4 個案例同時檢查初始化與設定更新。 |
| A07 | `core/whiteboard_manager.py` | 外部 Markdown 先 `read_bytes()` 整個讀入，再檢查大小，超大檔案仍可造成不必要的記憶體使用。 | 最多讀取上限加 1 byte，超限立即回傳驗證錯誤；測試 reader 拒絕無界讀取，確認白板不建立 active state。 |
| A08 | `core/assistant.py` | LLM timeout 的 NaN／Infinity 未回退，可能造成立即逾時或失去正常上限；正整數 normalization 對 Infinity 拋出未處理的 `OverflowError`。 | timeout 必須為有限正數；整數轉換捕捉 `OverflowError`；新增 8 個 normalization 案例。 |
| A09 | `core/assistant.py` | 純文字模式正常結束但沒有回覆時，先記錄 `llm_output status=completed`，之後才分類為 `empty_response`，造成紀錄互相矛盾。 | 在 output status 計算時辨識空回覆；強化原有空回覆測試，確認 failure、session refresh 與 output status 一致。 |

修補過程亦調整舊的 Claude Windows 啟動測試，使其 mock 新的 owned subprocess 介面；原本檢查 `CREATE_NO_WINDOW` 的斷言保留。

## 逐模組紀錄

下列路徑皆相對於 `ai_voice_assistant/`。

### 入口、設定與 utilities（6）

| Module | 檢查重點 | 結果 |
| --- | --- | --- |
| `main.py` | 啟動參數、GUI 啟動與例外清理 | 未新增修補 |
| `config.py` | layered config、merge、snapshot、寫入 | 未新增修補 |
| `private_state.py` | 私人狀態路徑與初始化 | 未新增修補 |
| `run_test.py` | pytest runner 與 exit code | 未新增修補 |
| `utils/logger.py` | handler、retention、欄位格式、LLM I/O 紀錄 | 未新增修補 |
| `utils/value_parsing.py` | bool 與序列化設定解析 | 未新增修補 |

### Core（18）

| Module | 檢查重點 | 結果 |
| --- | --- | --- |
| `core/assistant.py` | request generation、串流 timeout、取消、TTS worker、backend switch、關閉、heartbeat、排程與文字模式 | A08、A09 |
| `core/audio_capture.py` | callback、bounded queue、裝置啟停 | 未新增修補 |
| `core/audio_player.py` | PCM queue、residual、generation、interrupt、mute、stream 清理 | A02 |
| `core/state_machine.py` | 狀態轉移、hot-listen 時間與鎖 | 未新增修補 |
| `core/vad.py` | frame 累積、speech 判定、silence/reset | 未新增修補 |
| `core/wake_word.py` | model 路徑、stream/reset、keyword 輸出 | 未新增修補 |
| `core/sentence_builder.py` | pre-roll、句子收集、清理與 timeout | 未新增修補 |
| `core/transcriber.py` | local／Groq 分流、低信心過濾、fallback、背景載入 | 未新增修補 |
| `core/speaker_recognizer.py` | profile 載入、resample、辨識與非同步初始化 | 未新增修補 |
| `core/whisper_audio_archive.py` | 音檔寫入、retention 與路徑 | 未新增修補 |
| `core/heartbeat.py` | interval、start/stop、callback 例外 | 未新增修補 |
| `core/presence_tracker.py` | presence TTL、speaker 更新與鎖 | 未新增修補 |
| `core/schedule_models.py` | 排程狀態常數與 schema | 未新增修補 |
| `core/schedule_poller.py` | polling、取消、callback 例外 | 未新增修補 |
| `core/schedule_manager.py` | trigger 驗證、next run、claim/recovery、完成、報告、draft/undo、原子寫入 | 未新增修補 |
| `core/whiteboard_manager.py` | payload 路徑、Markdown／HTML、assets、大小限制、reload/hide/restore/close | A07 |
| `core/html_usage.py` | 每日額度、跨日重置、計時與持久化 | 未新增修補 |
| `core/session_settings.py` | 欄位型別、有限數值、SessionConfig snapshot | 未新增修補 |

### Pipeline（12）

| Module | 檢查重點 | 結果 |
| --- | --- | --- |
| `core/pipeline/__init__.py` | 公開介面 exports | 未新增修補 |
| `core/pipeline/messages.py` | Turn／PCM／結果資料結構 | 未新增修補 |
| `core/pipeline/arbitration.py` | 來源優先序、busy 與 preemption | 未新增修補 |
| `core/pipeline/cancellation.py` | cancellation scope 與 generation | 未新增修補 |
| `core/pipeline/queueing.py` | bounded queue、drop/coalesce 策略 | 未新增修補 |
| `core/pipeline/output_processor.py` | 非文字事件過濾、自適應 TTS chunk 上限 | A01 |
| `core/pipeline/latency.py` | monotonic 時間與 metrics snapshot | 未新增修補 |
| `core/pipeline/registry.py` | backend 註冊、alias、重複 ID | 未新增修補 |
| `core/pipeline/backends.py` | backend descriptors 與設定選取 | 未新增修補 |
| `core/pipeline/composition.py` | runtime 組裝 | 未新增修補 |
| `core/pipeline/coordinator.py` | 相容性介面 | 未新增修補 |
| `core/pipeline/runtime.py` | lease、active turn、generation、取消與 metrics 消費 | 未新增修補 |

### LLM（11）

| Module | 檢查重點 | 結果 |
| --- | --- | --- |
| `llm/base_client.py` | 共用 streaming／cancel／close 介面 | 未新增修補 |
| `llm/client_factory.py` | backend 選取與 runtime session state | 未新增修補 |
| `llm/process_owner.py` | Windows Job、suspended spawn、assignment 失敗清理 | 未新增修補；Claude 已接入此共用機制 |
| `llm/acp_stdio_client.py` | RPC futures、讀取迴圈、stream replay、permission、cancel、關閉 | 未新增修補 |
| `llm/codex_cli_client.py` | startup/auth/thread、RPC、turn lifecycle、取消 task 清理 | A03；保留原有 private-safe stderr logging 修改 |
| `llm/claude_code_client.py` | JSONL streaming、取消、程序樹、讀取限制 | A04、A05 |
| `llm/opencode_cli_client.py` | ACP 參數、runtime config、context files | 未新增修補 |
| `llm/grok_cli_client.py` | auth、ACP 設定、參數與子類整合 | 未新增修補 |
| `llm/antigravity_cli_client.py` | PTY argv、累積輸出去重、cache/session、取消與清理 | 未新增修補 |
| `llm/model_catalog.py` | CLI catalog、查詢取消、模型／effort 選項 | 未新增修補 |
| `llm/semantic_chunker.py` | token buffering、標點、flush/reset | 未新增修補 |

### TTS（5）

| Module | 檢查重點 | 結果 |
| --- | --- | --- |
| `tts/base.py` | synthesis/speak 共用契約與 interrupt | 未新增修補 |
| `tts/factory.py` | backend 設定、fallback 與路徑 | 未新增修補 |
| `tts/rate_limits.py` | 語速範圍、非有限值 | A06 |
| `tts/edge_tts_engine.py` | stream/cache、decode、retry、generation 與取消 | 未新增修補 |
| `tts/bluemagpie_tts_engine.py` | worker 啟停、request queue、回覆、timeout、audio 清理 | 未新增修補 |

### UI（16）

| Module | 檢查重點 | 結果 |
| --- | --- | --- |
| `ui/startup.py` | 設定草稿、model query token/cancel、欄位收集、準備期鎖定 | 未新增修補 |
| `ui/startup_window.py` | 背景準備、UI handoff、關閉與失敗清理 | 未新增修補 |
| `ui/main_window.py` | thread-safe UI dispatch、message queue、排程面板、白板、focus、keyboard guard、shutdown | 未新增修補 |
| `ui/session_window.py` | 文字排隊、固定輸入／輸出模式、HTML 額度、fullscreen、focus、關閉 | 未新增修補 |
| `ui/session_layout.py` | widget 連接、callbacks、輸入框與 panel layout | 未新增修補 |
| `ui/components.py` | virtual combo rows、事件 binding、popup／tooltip 清理 | 未新增修補 |
| `ui/session_theme.py` | 共用 widgets 與 state style | 未新增修補 |
| `ui/theme.py` | UI 常數 | 未新增修補 |
| `ui/animation_controller.py` | asset fallback、frame/cache、resize、timer 清理 | 未新增修補 |
| `ui/html_whiteboard.py` | localhost server、路徑限制、Edge owner、audio bridge、input forwarding、stop | 未新增修補 |
| `ui/embedded_html.py` | Edge embedding、native focus、keyboard capture、resize | 未新增修補 |
| `ui/markdown_host.py` | renderer ownership 與 clear | 未新增修補 |
| `ui/fullscreen_host.py` | native host resize、focus、關閉 | 未新增修補 |
| `ui/global_input_monitor.py` | hook／widget fallback、debounce、scope、stop | 未新增修補 |
| `ui/windows_job.py` | ctypes signatures、handle ownership、程序樹關閉 | 未新增修補 |
| `ui/window_environment.py` | 互動桌面判斷與 handle 釋放 | 未新增修補 |

### Tools 與公開 workspace template（9）

| Module | 檢查重點 | 結果 |
| --- | --- | --- |
| `tools/camera_tool.py` | 裝置／解析度解析、capture timeout、thread/container 清理、輸出 | 未新增修補 |
| `tools/bluemagpie_tts_worker.py` | model load、seed retry、silent audio、resample、PCM 與回覆 | 未新增修補 |
| `tools/opencode_auth_probe.py` | executable 檢查、timeout、finally 關閉與 exit code | 未新增修補 |
| `tools/grok_auth_probe.py` | auth probe、timeout、finally 關閉與 exit code | 未新增修補 |
| `tools/build_state_layers.py` | legacy assets、cutout、alignment、輸出路徑與 fallback 訊息 | 未新增修補 |
| `tools/build_generated_state_layers.py` | grid／strip 邊界、alpha、縮放與輸出 manifest | 未新增修補 |
| `agent_workspace_template/tools/schedule_tool.py` | CLI payload、state dir、JSON 結果與 exit code | 未新增修補 |
| `agent_workspace_template/tools/whiteboard_tool.py` | CLI payload、白板操作、結果與 exit code | 未新增修補 |
| `agent_workspace_template/tools/camera/camera_tool.py` | 公開 template wrapper 與入口路徑 | 未新增修補 |

## 驗證結果

在 `ai_voice_assistant/` 執行：

```powershell
.\venv\Scripts\python.exe -B -m pytest -q -rs -p no:cacheprovider
```

| 項目 | 結果 |
| --- | --- |
| 修補前基準 | 967 passed、10 skipped、2 warnings |
| 最終完整回歸 | **989 passed、10 skipped、2 warnings**（30.69 秒） |
| 正式 Python modules | 77 個均成功 strict UTF-8 讀取與 AST parsing |
| `pyflakes` | 未發現 undefined names；既有 unused imports／variables 未做無關清理 |
| `git diff --check` | 通過 |

10 個 skipped 均為 `tests/test_native_session.py` 的 opt-in Windows GUI 測試，需 `AI_GOVERNESS_NATIVE_TESTS=1`、已解鎖互動桌面及 Edge，並要求 serial 執行。本輪沒有開啟此 opt-in。

2 個 warnings 為既有第三方套件相容性提醒：`resemblyzer` 引用已 deprecated 的 SciPy import，以及 `webrtcvad` 使用 deprecated `pkg_resources`；本輪沒有改動 dependencies。

本輪驗證涵蓋自動測試、模擬 transport、音訊 callback 與本機假 CLI 子程序；未執行真實 LLM 帳號／雲端 TTS 呼叫、實體麥克風／喇叭／攝影機端到端測試，以及實際 Edge embedding／全螢幕鍵盤操作。這些仍需在實際使用環境驗收。
