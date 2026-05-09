# 語音合成層（TTS）

## `edge_tts_engine.py`

目前的 TTS 行為是「句子級緩衝播放」，不是 MP3 真串流解碼。

實際流程如下：

1. 接收一個句子字串
2. 使用 `edge_tts.Communicate(...).stream()` 下載該句完整 MP3
3. 把整句 MP3 放進記憶體緩衝
4. 交給 PyAV (`av`) 一次解碼成多段 PCM
5. 逐段把 PCM 推給 `AudioPlayer`

## 目前特性

- 使用 `voice`、`rate`、`volume` 參數建立 `edge_tts.Communicate`
- 預設採樣率是 24kHz
- 下載階段與播放前都會檢查 `interrupt_signal`
- 解碼後輸出的 PCM 會轉成 `int16`
- 會保留 `WordBoundary` 資訊，讓播放器能推估「已經播到哪一句、哪個詞」
- 遇到可重試的暫時性網路錯誤時，最多會重試 2 次

## 目前限制

- `tts.rate` 目前可由 UI 即時寫入並套用；`tts.volume` 雖然引擎已支援、`config.json` 也有欄位，但目前 UI 尚未提供調整控制
- 尚未做到邊收 MP3 chunk 邊增量解碼邊播放
