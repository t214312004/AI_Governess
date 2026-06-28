# BlueMagpie TTS Setup

BlueMagpie TTS is an optional experimental local TTS backend. The public default remains `edge-tts` because BlueMagpie has a heavier setup path and is currently much slower than `edge-tts` in normal interactive use.

Treat BlueMagpie as a local/offline fallback, not the recommended primary TTS backend. It is useful when cloud/network TTS is unavailable or when you explicitly want to test a local model and can tolerate higher latency.

This repository does not include BlueMagpie model files, prompt WAV files, speaker centroid `.pt` files, or voice samples. Those are local runtime assets and should stay private.

## Runtime Layout

The main app and BlueMagpie use separate Python environments:

- Main app: `ai_voice_assistant/venv`
- BlueMagpie worker: `ai_voice_assistant/.venv-bluemagpie`

This split is intentional. BlueMagpie has its own Python and GPU dependency constraints, so it should not be installed into the main app venv.

## Install The Worker Environment

From the repository root:

```powershell
cd ai_voice_assistant
py -3.12 -m venv .venv-bluemagpie
.\.venv-bluemagpie\Scripts\python.exe -m pip install --upgrade pip
```

Install CUDA PyTorch for your machine. The local test environment used CUDA 12.8 wheels:

```powershell
.\.venv-bluemagpie\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cu128 torch torchaudio
```

Then install the BlueMagpie package. This project was tested with the upstream repository commit shown below:

```powershell
.\.venv-bluemagpie\Scripts\python.exe -m pip install "bluemagpie-tts @ git+https://github.com/OpenFormosa/BlueMagpie-TTS.git@7d88ffd2224ef9cde7691724e512a5b6a325d431"
```

If you install a newer upstream commit, re-run the app tests and a local TTS smoke test before relying on it.

## Model Download

The worker uses `OpenFormosa/BlueMagpie-TTS` by default. If `ai_voice_assistant/models/bluemagpie` does not already contain a local model snapshot, the worker asks `huggingface_hub` to download the model into the Hugging Face cache.

If Hugging Face requires authentication or rate limits anonymous downloads, set an environment variable before launching the app:

```powershell
$env:HF_TOKEN = "your_huggingface_token"
```

Do not commit downloaded model files. `ai_voice_assistant/models/` is ignored by Git except for its README placeholder.

## Enable BlueMagpie In Local Config

Copy the public example config first:

```powershell
copy config.example.json config.local.json
```

Then edit `ai_voice_assistant/config.local.json`:

```json
{
  "tts": {
    "backend": "bluemagpie",
    "bluemagpie": {
      "enabled": true,
      "worker_python": ".venv-bluemagpie/Scripts/python.exe",
      "worker_script": "tools/bluemagpie_tts_worker.py",
      "model_dir": "models/bluemagpie",
      "device": "cuda",
      "warm_on_start": true,
      "request_timeout_seconds": 120,
      "speaker_centroid_path": "",
      "prompt_text": "",
      "prompt_wav_path": ""
    }
  }
}
```

`warm_on_start=true` loads the BlueMagpie worker before the GUI is shown. This makes startup slower, but it avoids paying the cold model load cost on the first spoken response. Sentence synthesis can still be slow after warmup; expect noticeably higher response latency than `edge-tts`.

If you start with `edge-tts` and later select `bluemagpie` in the UI, the setting is saved but takes effect after restart.

## Optional Voice Conditioning

BlueMagpie can run without local voice assets, but speaker identity may drift. For more stable output, provide both:

- `voice_profiles/tts_centroids/<your_style>.pt`
- `voice_profiles/tts_prompts/<your_prompt>.wav`

Then set:

```json
{
  "tts": {
    "bluemagpie": {
      "speaker_centroid_path": "voice_profiles/tts_centroids/<your_style>.pt",
      "prompt_text": "A short transcript matching the prompt WAV.",
      "prompt_wav_path": "voice_profiles/tts_prompts/<your_prompt>.wav"
    }
  }
}
```

These assets are ignored by Git. Treat them like private voice data unless you have a clear license and consent to publish them.

## Public Asset Policy

Do not publish local speaker centroid `.pt` files, prompt WAVs, generated reference WAVs, or real family voice samples in this repository.

Even when a prompt WAV is synthetic, redistribution rights may depend on the TTS service terms. A `.pt` centroid is also a voice-style asset. Keep those files local by default and document their source/license separately if you intentionally distribute them elsewhere.

## Smoke Test

After enabling BlueMagpie in `config.local.json`, run the app once from the repository root:

```powershell
.\start.bat
```

Expected behavior:

- Startup waits while BlueMagpie loads if `warm_on_start=true`.
- The UI appears only after warmup succeeds.
- If warmup fails, check `ai_voice_assistant/logs/` for `tts.bluemagpie.warmup_failed`.

For normal development validation:

```powershell
cd ai_voice_assistant
.\venv\Scripts\python.exe -m pytest -q
```
