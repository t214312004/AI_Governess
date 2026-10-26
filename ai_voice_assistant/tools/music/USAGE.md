# Music tools v1

此工具由 app 提供；先呼叫 `capabilities`／`styles`，不讀取或輸出 API key。
所有新音樂使用初始設定的 `lyria-3.5`，不切回 Clip。官方播放器不限 HTML 時間，一般遊戲仍有原配額。

## 創作

`generate --payload <workspace>/tool_payloads/music/<name>.json` 建立背景工作：

```json
{"request_id":"unique-user-request-id","title":"午後讀書時光","genre_ids":["jazz","hip-hop"],"style_notes":"Lo-fi","tags":["讀書"],"instrumental":true,"requested_duration_seconds":60,"prompt":"溫暖電鋼琴、柔和低音與輕鼓，約 78 BPM，無人聲或哼唱。"}
```

同一要求保留 request_id，重送不重複扣費。其他欄位可填 `lyrics`、`language`、`vocal_description`；純音樂不填歌詞。JSON 必須 UTF-8。`genre_ids` 可多選，使用 styles 的穩定 ID；模型選擇由 app 決定，不傳 model。
只有使用者要求創作才建立付費工作；僅要求播放時先 `list`，找不到才說明並釐清是否創作，不擅自生成。
`queued`／`running` 只表示正在創作；`job-status --job-id <id>` 的 `completed` 才表示已驗證入庫，並提供 track_id。
`cancel --job-id <id>` 可取消，但已送出的請求可能計費。`unknown_remote_result` 不自動重試。
已生成不等於指定秒數、完全無人聲或歌詞逐字正確，請讓使用者試聽。

## 曲庫與播放

- `list --genre-id jazz --genre-id hip-hop --genre-match any --limit 20`：符合任一風格；`all` 要同時具有每項。另有 `--query`／`--unclassified`。同首歌曲不重複列出。
- `show-player [--track-id <id>]`：在白板開官方播放器並選取曲目，會取代目前白板；不保證已播放。背景生成完成本身不會換掉白板。
- `player-status [--command-id <id>]`：取得 content_id、revision、track、position、volume、renderer heartbeat 和指定 command 狀態。
- `player-control --payload <workspace>/tool_payloads/music/<name>.json`：

```json
{"request_id":"unique-control-id","content_id":"<current content_id>","expected_revision":"<current revision>","action":"play","track_id":"<track_id>"}
```

action 可為 `play`、`pause`、`next`、`previous`、`seek`（position_seconds）、`set-volume`（volume 0–1）、`set-repeat`（repeat=none|one|all）、`set-filter`（genre_ids、genre_match=any|all、query、unclassified）。
先讀目前狀態，不猜 track_id／content_id。`accepted` 只是排隊；再查 command ack `applied` 才能說已套用。`needs_user_gesture` 時請按一次播放，不反覆重送繞過瀏覽器政策；過時或 unavailable 時刷新狀態。最後 `playing` 是播放器軟體回報，不能假裝已聽見喇叭聲音。

同時只允許一個尚未套用的播放指令。`busy` 表示前一指令仍在處理，先查其結果；不要當成成功或大量重送。使用者換歌、調音量、改篩選或播放狀態改變時 revision 會更新，舊指令會過期；一般播放進度心跳不會讓 revision 一直變動。
UI 與 agent 共用播放狀態。hide／restore／close 沿用 whiteboard_tool 的相同 content_id，隱藏與切換白板暫停音樂；restore 不會自動出聲。既有 private AGENTS 的一般白板入口限制不排除 app 新增的 music_tool show-player。

## 匯入與更正

`import --path <explicit-user-audio-path> --title <title> [--genre-id jazz]` 僅在使用者要求匯入指定音檔時使用。
`retag --track-id <id> --genre-id jazz --genre-id hip-hop [--title <title>]` 修改分類，不重生成歌曲。
曲庫永久保留；不直接修改 SQLite、whiteboard_state 或 metadata sidecars。12 種中英大風格保持可見，包括 0 首，細節放 style_notes，不擅自擴張兒童基本選單。

## 刪除與回收區

使用者明確要求刪除某首歌時，先 `list` 確認 track_id，使用 `delete --track-id <id>`；重名且無法判斷時才釐清。`deleted` 表示已從曲庫移到可復原的回收區，音檔保留。UI 同步停止被刪除曲目的播放，風格數量排除刪除歌曲。不要自行刪除其他歌曲。

`trash` 列出回收區；`restore --track-id <id>` 以原 ID、原音檔與分類恢復，不重新生成或計費。delete／restore 可安全重送。首版不提供永久清空，回收區仍計入本機容量。
