# Gemini API CLI 與音樂功能提交前 audit

日期：2026-10-26，Asia/Taipei。範圍是本次所有待提交的 Gemini API CLI 維護、音樂生成／曲庫／刪除、白板與初始 UI、agent 引導、測試、研究工具及交付文件。審查與測試使用暫存 workspace／設定及錄製或合成音訊替身，沒有新增付費 API 呼叫，也沒有修改本機歌曲或私人指引。

## 發現與修正

| 問題 | 修正與驗證 |
|---|---|
| 背景 worker 在歌曲發佈後再次寫入舊 metadata，可能覆蓋剛完成的更名／分類 | 將 elapsed metadata 合併到單次原子發佈，移除完成後的第二次覆寫；回歸測試在 publish 返回前執行使用者 retag，確認保留新值 |
| 驗證期間收到取消仍可能發佈歌曲 | 取消與發佈共用曲庫鎖，發佈前檢查工作；取消先取得鎖時不產生可被 recover 復活的歌曲 |
| 驗證、檔案處理較慢時租約可能到期；失去租約後仍可能取得排隊工作 | 獨立 heartbeat 在驗證期間更新自己持有的租約；claim 在 transaction 內重新核對 owner；停止訊號先於資料庫存取檢查 |
| Windows 檔案占用使 staging 清理失敗，可能中止整個 worker | 清理改為 best effort，保留已完成音檔並繼續下一項；限定只清理當前工作 UUID 的 staging 目錄 |
| 播放器 UI 已換歌或調整狀態，舊 agent 指令仍可能被套用；多個指令共用同一 revision | UI 重要狀態改變會更新 revision；舊指令過期，一次僅接受一個待套用指令；前端先同步狀態，再檢查 revision 與快照；播放進度心跳不會一直改 revision |
| 選取正在播放的同一首歌時，軟體回報暫停但 native audio 可能仍在播 | select 一律先 pause；新增原生 Edge 播放測試，核對選曲後進度停止且音量保留 |
| 異常 localStorage 音量或資料型別可能讓頁面初始化失敗 | 驗證 saved object／genres 與 finite volume，錯誤值回到有效預設 |
| 同時匯入可越過容量檢查 | 容量檢查與發佈共用曲庫鎖；以兩個真實 WAV 並發驗證只能一首成功入庫 |
| 損壞 sidecar／journal 或未知 SQLite schema 可能中斷恢復或錯誤重建 | 驗證恢復資料的 ID、路徑、hash、名稱、時間與風格；無效刪除 journal fail closed；未知 schema 保留版本並拒絕降級 |
| 曲庫資料庫無法寫入時，renderer.stop 可能無法清理 Edge／HTTP server；profile 無法建立可能影響對話啟動 | stop 使用 finally 清理 owned renderer；profile 建立成功後才啟動 worker；HTTP 回傳不含私人診斷的 503 JSON |
| 空白、程式或磁碟根目錄被當成曲庫位置，可能把私人資料散落在公開目錄 | runtime 與初始設定都要求專用資料夾；測試確保不會在程式根目錄建立 SQLite |
| 研究工具可把音訊寫進未 ignored 的位置，且 debug 環境變數可能影響 CLI 輸出 | 限制 probe output 在 ignored tool_payloads；結果原子保存，移除繼承的 debug／其他認證環境變數 |
| 提交前 audit 僅靠預設 private paths，可能漏掉自訂位置匯出的音檔／SQLite | 增加全 repo 已 tracked／staged 音檔與 SQLite 副檔名攔截；以暫存 Git repo 測試誤加入會被拒絕 |
| 文件截圖的實際格式是 JPEG，檔名卻為 PNG | 更正副檔名與文件引用，未修改圖片內容；確認沒有 EXIF／定位資料 |

## 驗證結果

- 全套一般回歸：**1321 passed、37 skipped、3 warnings，42.94 秒**。略過的是選用／環境相關測試；warnings 來自既有 Torch、SciPy、webrtcvad dependencies。
- Windows 原生 UI／CLI 組合：**70 passed，147.09 秒**，涵蓋初始設定保存／查詢／取消、Edge attach、HTML 額度 0／error 時的音樂播放器、聊天焦點、hide／restore／close、實際 agent 播放指令與同曲選取暫停。
- 新增 audit 回歸測試涵蓋發佈、取消、租約、cleanup、儲存容量、舊指令、損壞資料、錯誤 profile／資料庫與未知 schema；全部通過。
- Python AST、JSON parse、strict UTF-8／NUL／replacement character、JavaScript `node --check` 及 `git diff --check` 通過。
- 測試不覆寫 private AGENTS／TOOLS；原生 music 測試使用獨立 ephemeral origin，避免占用使用者正式播放器的 port／profile。

可重跑指令：

```powershell
cd ai_voice_assistant
$env:PYTHONDONTWRITEBYTECODE='1'
$env:AI_GOVERNESS_DISABLE_LOGGING='1'
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
$env:AI_GOVERNESS_NATIVE_TESTS='1'
.\venv\Scripts\python.exe -m pytest -q -s -p no:cacheprovider tests/test_native_session.py tests/test_gemini_api_cli.py tests/test_startup_usability.py
```

## 提交範圍與界線

提交只包含程式、測試、設定範本、工具指引、研究／驗證文件和隔離 UI 截圖。歌曲、SQLite、回收區、生成暫存、API key、config.local.json 與 private agent workspace 都保留在本機；music_library 只允許 README placeholder。既有使用者試聽結果與費用紀錄仍放在 ignored tool_payloads。

stage 後重新執行 pre_git_audit 與 staged blob 私密資料檢查，通過後才 commit／push。審查與測試沒有發現尚未處理、會阻擋本次提交的問題；這不代表能保證所有環境與未來外部 API 行為。

本次 stage 共 54 個檔案，逐一檢查 Git index 內的實際 blob：28 個 Python AST、5 個 JSON 與其餘文字／圖片格式有效，未發現本機設定或環境變數中的 API key、音訊 binary、SQLite 或內嵌 base64 媒體。pre_git_audit 回報 `[OK]`，staged diff whitespace 檢查通過；已 fetch 確認起點與 origin/main 相同，push dry-run 可用。
