# 文件、Sophia 提示詞與白板工具核對

日期：2026-10-05。核對依據是本機 source、public config、測試與目前 UI 素材；
這份紀錄描述本次工作結果，外部 CLI、裝置與服務是否可用仍須在使用時確認。

## 核對範圍與修正

已檢查 repository 原有的 31 份 Markdown，包括兩份主要 README、所有 docs、模組說明、
runtime placeholder、公開 Sophia workspace template、contributing／security／license
及 issue templates；另檢查實際 private workspace 的 AGENTS、TOOLS、camera 說明與工具入口。
私人家庭資料、記憶、遊戲進度與既有 GUI 白名單保留。

| 項目 | 現行契約與文件修正 |
| --- | --- |
| 正式 UI | `main.py` 經五步初始設定進入 `session_window`；暖白／木棕／霧藍，左側角色或白板、右側純文字對話、多行輸入與圖示控制。既有 UI screenshot 符合目前設計。 |
| 設定與退出 | backend、model、effort、STT／TTS、輸入／輸出、字級與額度在啟動時決定；主畫面沒有設定抽屜或切換入口，Alt+F4 關閉後重啟調整。 |
| 文字與語音 | Enter 換行、Ctrl+Enter 送出；busy 仍可打字，FIFO 最多 10 則／每則 8,000 字。輸入與輸出獨立，打字也可能朗讀；麥克風／播音各自靜音。 |
| 白板 | 隱藏保留內容，關閉清除；HTML 隱藏卸載、恢復／reload 重載，未存入 `localStorage` 的頁面記憶不保留。manager state 不證明 renderer 成功或實際畫面。 |
| 排程與 heartbeat | `SchedulePoller` 獨立輪詢到期任務；一般 heartbeat 僅讀既有 context，不執行排程或寫回記憶。新增 [排程指南](schedule.md)，補齊 payload、trigger、確認／undo 與報告邊界。 |
| 工具能力 | whiteboard／schedule／camera 是 shell CLI wrappers；其他搜尋、看圖、瀏覽器或裝置控制依 backend／安裝／授權。拍照是單張，結果需檢查 JSON，不能宣稱持續監看。 |
| TTS／其他設定 | 說明 optional progressive decode、啟動設定可調 TTS rate／volume、Claude public permission mode 與 class fallback 的差別，以及 speaker enrollment 最小樣本設定。 |
| 提示詞同步 | 公開與本機 private AGENTS／TOOLS、whiteboard wrapper、camera 說明同步必要契約；共同 prompt 補上規則載入、UI／輸出狀態與白板 metadata 邊界。bootstrap 仍只補缺少檔案。 |
| 歷史 audit | 保留過去的結果及測試數字，標示為快照並連到現行指南；新增 [文件索引](README.md)。 |

## 新增白板操作與額度查詢

- `hide [--content-id …]`／`restore [--content-id …]` 與 UI 按鈕共用持久化 `hidden` state；
  保留 content id／內容，跨重啟保存。重複操作不重建文件，舊 content id 不會修改較新的白板。
- `status` 在 active 或 empty 時都提供 `html_quota`：每日上限、已用與剩餘秒數、
  available、status、timezone 及可讀原因。`available`／`exhausted`／`disabled`／`error`
  區分可用、用完、額度設為 0、紀錄讀寫失敗；error 的秒數是 null，不能解讀成 0。
- `show-html`／HTML `restore` 被額度阻擋時回傳 `blocked`、`block_reason`、同一份
  `html_quota` 與 `message_for_user`。恢復失敗保留隱藏內容，可在隔日額度恢復後再開啟。
- 用量是最近保存的快照；只計 renderer 實際可見時間，隱藏、關閉、桌面鎖定或睡眠不扣。
  詳細操作及 JSON 範例見 [HTML 白板指南](html_whiteboard.md)。

## 驗證結果

| 驗證 | 本次結果 |
| --- | --- |
| 完整回歸 | `venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider`：958 passed、10 skipped、2 warnings（30.15 秒）。warnings 來自第三方 `resemblyzer`／`webrtcvad` 的 deprecated APIs。 |
| 白板與 prompt 回歸 | 覆蓋三種內容的 hide／restore／重啟保留、stale content id、HTML 額度秒數與三種拒絕原因、CLI action、UI 輪詢及 Markdown widget 保留；包含完整回歸。最後微調 prompt 用詞後，`tests/test_assistant.py` 另通過 190 tests。 |
| 原生 Windows UI | `AI_GOVERNESS_NATIVE_TESTS=1`：7 passed、3 failed。通過的案例包含 Markdown／圖片、輸入、隱藏與恢復；3 個 HTML 案例因 Edge 視窗附著／尺寸校正逾時失敗。 |
| 原版本對照 | 以 Git HEAD 的原版 `session_window` 重跑 HTML hide／restore 案例，也因 Edge 啟動逾時失敗。本次尚不能宣稱 HTML 原生 UI 驗證通過，需在 Edge 能正常附著的互動桌面再驗證。 |
| 文件與檔案 | 34 份公開 Markdown strict UTF-8、40 個 local links、14 份 JSON 範例、12 個修改 Python 的 AST、公開／private 共用提示詞段落及 whiteboard wrapper 同步檢查，均無錯誤；`git diff --check` 通過。 |
| Git 私人資料 audit | `scripts/pre_git_audit.ps1` 回傳 `[OK] No private paths tracked`；private workspace 修改維持 Git ignored，提交範圍限公開 source、template、測試與文件。 |

完整測試時另重現了既有的 CLI 查詢取消競態：取消已設定仍啟動 subprocess，Windows
清理暫存檔時可能發生 sharing violation。`CliCatalog._run` 加入啟動前取消檢查，
並以不啟動 subprocess 的回歸測試驗證。

本次沒有以真實家庭對話、mic／camera 擷取或外部服務呼叫驗證。提示詞與新 Python
行為需重啟 app／建立新 session 後載入。
