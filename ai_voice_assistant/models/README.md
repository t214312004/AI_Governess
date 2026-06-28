# Models

Downloaded model files are local runtime artifacts and are ignored by Git.

The default wake-word detector expects this directory:

```text
models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01
```

Use the repository script from the project root:

```powershell
.\scripts\download_models.ps1
```

The current wake-word model declares `Apache License 2.0` in its bundled README. If you replace it with another model, check that model's license before redistributing it.

Optional BlueMagpie TTS model files may also live under:

```text
models/bluemagpie
```

Those files are local runtime artifacts and must not be committed. See `docs/bluemagpie_tts_setup.md` for setup details.
