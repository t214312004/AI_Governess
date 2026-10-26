# 音樂功能調整：風格入門、刪歌與音量

## 完成結果

- 本機 12 種風格都至少有一首可播放、只屬於該風格的入門示範。保留原本作品與使用者已試聽接受的三首新曲；搜尋「風格入門」可集中查看。細部曲目、ID、音檔 hash、prompt、歌詞與審聽結果只在 ignored 本機證據內，本文不複製這些私人內容。
- 新增刪除／回收區／復原。UI 每首歌的「⋯」內有刪除入口及確認視窗；可在回收區找回原音檔，不再生成。
- 修正音量滑桿被白板 audio bridge 蓋回初始音量的 bug；UI 滑桿與 agent `set-volume` 都能持續生效，且保留 ducking 與 header 靜音。

## 單一風格曲庫

12 種大分類為兒歌、流行、搖滾、爵士、藍調、嘻哈、電子、古典、民謠、鄉村、拉丁、傳統音樂。各自以 `genre_ids=[單一 ID]` 保存，並逐首核對原始要求、音訊可解碼、非靜音與 hash。

既有曲庫中已有一首單一風格兒歌，因此先補另外 11 類。生成器有時會偏離曲風／配器，不能只看標籤判定；本次再做有限的改稿，使用 Gemini 3.8 Flash 盲聽及 Gemini 3.1 Pro 音訊交叉檢查，後者也評估作為單一大分類入門曲的適合度。分析模型對部分曲目有明顯不一致；相關不確定性保留在本機紀錄。使用者實際試聽三首後回覆「都 OK」，這三首按真人回饋保留，不以自動分析覆蓋其偏好。

目前正式曲庫 22 首，其中 14 首有單一風格入門標籤，12 類均至少一首。這次未採用的 7 首初稿移到可復原回收區，原本的歌曲保留。新曲統一 Lyria 3.5，沒有改用其他音樂模型；其他 Gemini 模型僅用於音訊評閱。

本批有 22 次提交、20 次完成、2 次遠端結果未知。沒有自動重送未知結果的原請求；改稿使用不同內容與新 request_id。按既有每次 US$0.08 定價快照估算，生成約 US$1.60–1.76，另有音訊分析費用；沒有查 Billing 實付。這次為使用者明確要求的批次採一次性記憶體額度，未提高 `config.local.json` 的平常每日上限。

本機證據在 `tool_payloads/music_style_library_final.json`、`pure_style_seed*_results.json`、`pure_music_reviews.json`、`music_style_crosscheck.json`。這些檔案、實際音檔與回收區均不進 Git。

## 刪除／復原契約

`MusicManager` 的 `deleted_tracks` 表保存回收區，`trash/<track_id>.json` 保存原子寫入的刪除／復原意圖。原音檔保留以便復原，新的 audio 請求不再提供刪除曲目，曲庫與風格統計也排除它。回收區仍計入容量。

delete、restore、retag 與 recover 共用本機檔案鎖；SQLite transaction 管理索引與播放狀態。崩潰後 recover 遵循 journal，不讓被刪歌曲因 metadata 掃描而復活；延遲 worker 寫入也不會恢復刪除曲目。復原沿用 ID、hash、名稱及分類；重送操作維持相同結果。

刪除當前曲目時，UI 立即 pause、移除 src 並清掉選曲；後端讓相關待執行播放指令過期、清掉選曲並等待 renderer 更新狀態。其他曲目播放不受影響。工具 `delete --track-id`、`trash`、`restore --track-id` 與 HTTP `/api/delete`、`/api/restore` 共用同一 manager。HTTP 沿用 Host、Origin、nonce 及 active board 檢查；agent 引導與 public workspace template 已更新，private 指引不覆寫。

## 音量 bug 原因與修正

原本 `HTML_AUDIO_BRIDGE` 用 WeakMap 只記住 `<audio>` 第一次出現的 volume，並每 100 ms 以這個舊值乘上 ducking 比例。播放器直接改 `audio.volume` 後，下次輪詢就被蓋回。

新增 `__aiGovernessSetMediaVolume(element, value)` 更新最新的基礎音量；music 的 UI 滑桿、agent 控制與重載還原均呼叫同一個 `setUserVolume`。自動 ducking／靜音只套乘數，不更動使用者選擇，也不改 Windows 系統音量。一般 HTML app 保持既有行為，新增 API 僅供主動接入的媒體控制使用。

實際頁面驗收讀到：滑桿 5% 在輪詢後仍保留；agent 改 35% 有 applied ack；duck 比例 20% 時 native media volume 為 0.07；靜音時為 0，取消靜音回到 0.35；重新載入保留 35% 且維持暫停。測試頁使用本機隔離曲庫與 test-only DOM probe 讀取 native property，正式 UI 沒有加入診斷面板。

## 驗證

- 全套一般回歸：**1294 passed、36 skipped、3 warnings**。warnings 來自既有 dependencies。
- 最後相關回歸 **61 passed**，Windows 原生 music **2 passed**；涵蓋 HTML quota=0/error、Edge attach、聊天焦點與 hide/restore/close。
- 刪除、復原、索引重建、被中斷的刪除／復原、延遲 worker、HTTP 音檔 404／還原後 206、重複操作、路徑拒絕、agent CLI 均有回歸測試。
- Node 執行真正的 bridge script，驗證基礎音量、連續輪詢、ducking、靜音期間調整與還原。
- 瀏覽器實際操作刪除正在播放的測試歌曲，確認停播、曲庫數量減少、回收區增加，再恢復同 ID；390×844 刪除視窗無橫向溢出。

本批不 commit 或 push；音樂、SQLite、回收區與私人證據只留本機。提交前的 `pre_git_audit.ps1` 也涵蓋整個 `music_library/`，唯一允許的例外是 README placeholder。

最後 `git ls-files` 沒有曲庫音檔／資料庫，`git check-ignore` 確認音檔、SQLite、回收區與 tool_payloads 受排除，audit 回報 `[OK]`。50 個變更／新增檔案的 key 比對與文字編碼檢查無異常，JS 語法與 diff whitespace 檢查通過。需重啟 app 才會載入新的音量與刪除介面。

以下是隔離驗收畫面，只含測試歌曲名稱；不是私人曲庫截圖。

![刪除確認視窗](assets/music_delete_2026-10-26.jpg)
