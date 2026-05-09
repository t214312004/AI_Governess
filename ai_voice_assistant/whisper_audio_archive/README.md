# Whisper Audio Archive

若 `config.json` 中的 `whisper_audio_archive.enabled` 為 `true`，每次送進 Whisper 的語音都會先存到這裡。

輸出內容：

- `utterance_*.wav`: 原始送件音檔
- `utterance_*.txt`: 同名文字索引；只有在 `write_transcript_sidecar = true` 時才會寫出，內容包含 `utterance_id`、`wav_path`、`speaker_name` 與 `transcript`

你之後可以直接從這裡挑出有代表性的 `.wav`，
再複製到 `voice_profiles/<EnglishName>/` 之下。
