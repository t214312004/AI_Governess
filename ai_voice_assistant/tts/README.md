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

- `tts.voice`、`rate`、`volume` 與 backend 在初始設定「進階設定」調整，本次 session 不提供即時設定切換；主畫面播音圖示只控制靜音
- progressive decode 仍以累積 MP3 資料重新解碼，效能依句長、網路與 CPU 而異；不要視為零延遲保證

## `bluemagpie_tts_engine.py`

BlueMagpie TTS 是選用的 local experimental backend。它使用獨立 worker process 與獨立 venv：`ai_voice_assistant/.venv-bluemagpie`。

目前 BlueMagpie 生成速度偏慢，不適合作為日常主力 TTS；建議定位為 local/offline fallback，或用於測試本機模型與 voice conditioning 設定。

公開 repo 不包含模型、speaker centroid `.pt`、prompt WAV 或 reference WAV。完整啟用方式請看 [BlueMagpie 設定指南](../../docs/bluemagpie_tts_setup.md)。
