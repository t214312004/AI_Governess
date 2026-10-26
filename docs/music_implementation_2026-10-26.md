# Gemini API CLI 與音樂播放器實作紀錄

後續已加入單一風格示範、刪除／回收區／復原及音量修正；更新內容與新的測試數字見[追加調整紀錄](music_updates_2026-10-26.md)。本文保留第一階段實作時的結果。

日期：2026-10-26，Asia/Taipei。實作依[原始研究與規劃書](gemini_api_cli_music_plan_2026-10-26.md)及使用者後續要求。操作方式見[音樂小天地](music.md)。

## 已交付範圍

| 需求 | 實作 |
|---|---|
| 初始 UI 更新 CLI、查詢模型、指定所有音樂模型 | `ui/gemini_api_settings.py`、`utils/gemini_api_cli.py`；Windows 官方 portable release、digest 驗證、可取消、唯讀查詢，保存 `music.model=lyria-3.5` |
| 原創音樂 | `utils/gemini_music.py`；固定 Lyria 3.5、prompt file、`store:false`、key 僅傳 child env、限制逾時與輸出；沒有模型降級或付費自動重試 |
| 背景工作 | `core/music_worker.py`；SQLite lease 單一 worker、排隊、取消、重啟後標示未知、完成通知與確認、成功後清理 scoped staging |
| 永久曲庫 | `core/music_manager.py`；UUID、SQLite、atomic audio／metadata publication、SHA-256、PyAV 全檔解碼、可重建索引、保留遺失音檔紀錄 |
| 兒童雙語風格 | `assets/music_styles.v1.json`、`core/music_catalog.py`；12 種大分類、簡介、aliases、多對多與 ANY／ALL 篩選 |
| 漂亮且可操作的播放器 | `ui/music_player/`；暖白與木色、霧藍控制、黑膠卡片、風格探索、搜尋、創作／更名表單、固定播放列、手機版、鍵盤焦點與 reduced motion |
| 白板免 HTML 時間 | `WhiteboardManager.show_music()`、獨立 `MusicPlayerRenderer`；固定內建入口，HTML 額度零／耗盡／故障不 gate，也不扣秒數 |
| agent 創作與播放 | canonical `tools/music_tool.py`、`tools/music/USAGE.md`、`llm/music_context.py`；五種 backend 共用 app prompt，舊私人指引不覆寫 |
| 實際播放回報 | content_id／revision、12 秒 command TTL、request_id 去重、renderer heartbeat、`accepted/applied/needs_user_gesture/error/expired` 明確區分 |
| 媒體與本機邊界 | 僅監聽 127.0.0.1，固定資產、scoped UUID audio、Range／HEAD、Host／Origin／nonce、CSP、manifest 不傳 key／音檔路徑／原始 prompt |
| 隱私與費用 | Git ignored 曲庫、audit placeholder、每日次數與估價上限、總容量限制、無 key 仍可播放；沒有修改 Billing 或訂閱 |

TTS 保留現行 Python 直接呼叫與串流路徑。前期實測沒有支持為降低延遲而改用 `gemini-api tts`。

## 真實生成與播放驗收

先前使用者接受的五首測試作品已複製到正式永久曲庫，原始試聽資料保持原樣。既有 Clip 歷史作品仍能播放；所有後續新生成只用 Lyria 3.5。

新增驗收曲〈雨後花園的小探險〉：

- 模型 `lyria-3.5`，風格 `children + folk`；要求輕快木吉他與木琴、純音樂、約 45 秒。
- 新 CLI 流程連同本機驗證與入庫約 **89.26 秒**。
- 完整解碼後長度 **60.839 秒**，MP3 **1,466,266 bytes**；正式 `track_id=0d94713a41184d5bb25399faefea7606`。
- SHA-256：`031c5b8231db233e1682038ad6343d6148ec0674024d63ce2eec8bb00eb53345`。
- 已在正式原生白板的內嵌 Edge 實際操作播放。讀到軟體回報 `playing`，agent 播放要求收到 `accepted` 後，頁面回報相同 command_id 的 `applied`，revision 更新；沒有把工具入列當播放證據。
- 生成檔案可播放，不代表新曲人聲、樂器與風格已經過真人鑑定。已保留「未確認」review 狀態，可直接從曲庫試聽。

驗收初次提交遇到 cancellation interface 少了 `wait()` 的整合錯誤，工作如實記為 `unknown_remote_result`，沒有自動重試。修正 Event 介面並加入回歸測試後，另一次受控驗收提交成功。兩次提交均保守計入當日限制；成功一首定價估算 US$0.08，初次請求是否到達遠端／計費無法由本機結果確定，保守上界再計 US$0.08；未查 Billing 實付。

本機私有證據：`tool_payloads/music_acceptance_result.json`、`music_player_ack_result.json`，正式歌曲在 ignored `music_library/`。沒有把 key、音訊或私人記憶提交到公開 source。

## 驗證

一般測試使用 `PYTHONDONTWRITEBYTECODE=1`、`AI_GOVERNESS_DISABLE_LOGGING=1` 和 pytest `-p no:cacheprovider`。測試涵蓋：

- 12 種空曲庫風格、中英搜尋、多風格去重／ANY／ALL、未分類。
- queue 並發去重、payload conflict、次數／費用／容量限制、取消、lease、未知結果不重試。
- 音訊驗證、原子發布中斷與恢復、retag、多次重開、檔案遺失。
- 控制前置條件、stale content／revision、TTL、實際 ack、autoplay 手勢、隱藏停止。
- HTTP Range 206／416／suffix、HEAD、路徑與資產邊界、Origin／Host／nonce、無效 JSON／狀態。
- 五種 backend 共用提示含 canonical tool；既有 private guide 不更動，曲庫錯誤不阻斷一般對話。
- provider 只用 Lyria 3.5、key 不在 argv、store:false、有限逾時、外部路徑拒絕與不重試。

原生驗證選用 `AI_GOVERNESS_NATIVE_TESTS=1`，使用暫存設定／workspace，不啟動真人 LLM 或錄音。啟用原生 UI 的測試組合共 **69 passed**（含 CLI 的非 UI 回歸），涵蓋初始 UI、Gemini CLI 與 session；包含新增的 music quota=0／error、Edge attach、輸入框焦點、hide／restore／close。最後亦重跑兩項 music 原生案例，**2 passed**。

另以 computer-use 操作正式 native renderer 的播放、重新載入、風格頁與創作表單；以瀏覽器在隔離曲庫驗證 1024×900 桌面與 390×844 窄版，沒有橫向溢出，窄版保留全部英文名稱。`pop+electronic` 的 ANY 得 3 首、ALL 得 1 首，沒有重複。隔離表單使用錄製音訊替身完成 queue → 入庫 → UI 更新，沒有再送付費 API；該測試歌曲不在正式曲庫。

最終一般回歸：**1285 passed、36 skipped、3 warnings，34.19 秒**。36 項 opt-in 測試在一般模式略過；原生組合另依上述方式啟用。三項 warning 來自既有 Torch／SciPy／webrtcvad dependencies。

```powershell
cd ai_voice_assistant
$env:PYTHONDONTWRITEBYTECODE='1'
$env:AI_GOVERNESS_DISABLE_LOGGING='1'
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
$env:AI_GOVERNESS_NATIVE_TESTS='1'
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_native_session.py tests/test_gemini_api_cli.py tests/test_startup_usability.py
```

`node --check ui/music_player/player.js`、strict UTF-8／replacement character／NUL 檢查、本機 API key 對所有交付檔案的內容比對、`git diff --check` 均通過；`pre_git_audit.ps1` 回報 `[OK]`。只有 music_library/README.md placeholder 可進 Git，實際音樂／SQLite／暫存均 ignored。未執行 commit 或 push。

## 實際限制

- Edge 音訊走 Windows browser 的系統輸出，未承諾跟隨 Python TTS 的指定裝置。
- 瀏覽器 autoplay 政策、喇叭靜音或硬體音量不能由 `playing` 回報保證；需要時請使用者按播放或檢查輸出。
- App 關閉時背景 worker 會取消自己擁有的 CLI；不提供 Windows service。送出後取消可能計費。
- 生成時只回報狀態，不捏造完成百分比、精準 ETA、歌詞逐字吻合或樂理鑑定。
- 風格細節用 notes／tags，首版不擴張成數百個流派；新增大風格需要更新 versioned catalog。
- 首版提供匯入及分類更正 CLI，沒有自動刪歌、遠端分享、雲端同步或廣泛音檔目錄掃描。
