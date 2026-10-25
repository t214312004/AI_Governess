# 語音合成層（TTS）

## `edge_tts_engine.py`

Edge TTS 有兩種解碼路徑，由 `pipeline_v2_5.streaming_tts` 選擇；public default 為 `false`。

實際流程如下：

1. 接收一個句子字串
2. 使用 `edge_tts.Communicate(...).stream()` 下載該句完整 MP3
3. 把整句 MP3 放進記憶體緩衝
4. 交給 PyAV (`av`) 一次解碼成多段 PCM
5. 逐段把 PCM 推給 `AudioPlayer`

啟用 streaming TTS 時，`synthesize_stream()` 在累積足夠 MP3 bytes 後，以 PyAV 解碼目前收到的資料並只輸出新增的 PCM，不必等待整句下載完。門檻由 `pipeline_v2_5.streaming_decode_min_bytes` 設定。v2.5 pipeline 將合成與播放放入 bounded queues，帶入 turn／generation，避免取消後播放舊音訊。

`edge-tts` 使用 Microsoft 的線上語音服務：待合成文字會離開本機並傳送至該服務。需要離線處理時，請改用 experimental BlueMagpie backend。

## 目前特性

- 使用 `voice`、`rate`、`volume` 參數建立 `edge_tts.Communicate`
- 預設採樣率是 24kHz
- 下載階段與播放前都會檢查 `interrupt_signal`
- 解碼後輸出的 PCM 會 resample 到設定的輸出取樣率，clip 後轉成 `int16`
- 會保留 `WordBoundary` 資訊，讓播放器能推估「已經播到哪一句、哪個詞」
- 遇到可重試的暫時性網路錯誤時，最多會重試 2 次

## 目前限制

- backend 及 Edge 的 `tts.voice`、`rate`、`volume` 可在初始設定「輸入與輸出」調整，其餘參數在「進階設定」；本次 session 不提供即時設定切換，主畫面播音圖示只控制靜音
- progressive decode 仍以累積 MP3 資料重新解碼，效能依句長、網路與 CPU 而異；不要視為零延遲保證

## Edge TTS 連線回傳 HTTP 403

若文字回覆正常，但 log 出現 `WSServerHandshakeError: 403`，請先檢查 `venv` 中的 `edge-tts` 版本。`7.2.8` 使用的舊版 `Sec-MS-GEC` token 已無法通過目前服務的驗證；[上游 7.3.0](https://github.com/rany2/edge-tts/releases/tag/7.3.0) 已加入 v2 token 支援，本專案使用 `7.3.1`，同時包含 server date 的 locale parsing 修正。

關閉 app 後，在 `ai_voice_assistant/` 目錄執行 `./venv/Scripts/python.exe -m pip install "edge-tts==7.3.1"`，再重新啟動。這會更新既有 `venv` 中的套件；只修改 `requirements.txt` 不會更新已安裝的版本。

## `gemini_tts_engine.py`

Google API 的選用 backend，預設模型為 `gemini-3.8-flash-tts`、voice 為 `Leda`。`pipeline_v2_5.streaming_tts` 選擇 SSE PCM 串流或完整 PCM／WAV；來源音訊經 PyAV 重採樣到播放器取樣率。style 與朗讀內容分開傳送，不送 thinking 或 Edge 的 rate／volume。

engine 保留 turn／generation，總長未知時不虛構字級播放進度。首音、idle 與總 deadline 可取消；交出音訊後失敗不重播，同一失敗回覆也不繼續合成後續分段。預設最短呼叫間隔 8 秒，搭配 Gemini 專屬分段參數以降低限流；所有參數可在初始 UI 調整。

初始設定提供 key 儲存／刪除、音色搜尋與試聽；詳細設定、quota 取捨及實測限制見 [Gemini 語音指南](../../docs/gemini_audio_setup.md)。待合成文字會傳給 Google，取消本機網路讀取不保證停止供應商計費。

## `bluemagpie_tts_engine.py`

BlueMagpie TTS 是選用的 local experimental backend。它使用獨立 worker process 與獨立 venv：`ai_voice_assistant/.venv-bluemagpie`。

目前 BlueMagpie 生成速度偏慢，不適合作為日常主力 TTS；建議定位為 local/offline fallback，或用於測試本機模型與 voice conditioning 設定。

公開 repo 不包含模型、speaker centroid `.pt`、prompt WAV 或 reference WAV。完整啟用方式請看 [BlueMagpie 設定指南](../../docs/bluemagpie_tts_setup.md)。
