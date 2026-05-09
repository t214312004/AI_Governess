# Contributing

Contributions should only include public source code, tests, documentation, or non-private sample assets.

Before opening a patch:

1. Run tests from `ai_voice_assistant/`.
2. Check that no private files are staged.
3. Avoid committing generated audio, logs, local memory, model downloads, or credentials.

Recommended checks:

```powershell
cd ai_voice_assistant
.\venv\Scripts\python.exe -m pytest -q
cd ..
.\scripts\pre_git_audit.ps1
```

If you add a dependency, update the relevant requirements file and `THIRD_PARTY_NOTICES.md`.
