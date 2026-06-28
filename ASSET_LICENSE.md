# Asset License Notes

Source code is covered by `LICENSE`.

Visual, audio, model, and generated assets may have separate rights and provenance:

- Runtime state images under `ai_voice_assistant/assets/states/layers/*.png` are included for this app. If you replace or redistribute them separately, document their source and license.
- Generated source images, diagnostics, preview layers, and intermediate sprite sheets are ignored by Git.
- Voice samples under `ai_voice_assistant/voice_profiles/` are private user data and must not be committed.
- BlueMagpie TTS speaker centroids (`*.pt`), prompt WAVs, and reference WAVs under `ai_voice_assistant/voice_profiles/tts_*` are private voice-style assets by default and must not be committed unless you have a clear license and consent to redistribute them.
- Microphone recordings under `ai_voice_assistant/whisper_audio_archive/` are private user data and must not be committed.
- Downloaded model files under `ai_voice_assistant/models/` are ignored. Follow each model's own license.
