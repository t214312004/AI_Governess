# Security

This project can interact with microphones, speakers, keyboard/mouse activity, local LLM CLIs, and optional camera tooling. Treat it as local automation software, not as a sandbox boundary.

## Private Data

Do not commit:

- `ai_voice_assistant/config.local.json`
- `ai_voice_assistant/logs/`
- `ai_voice_assistant/whisper_audio_archive/`
- `ai_voice_assistant/voice_profiles/`
- `ai_voice_assistant/agent_workspace/*.md`
- downloaded model files under `ai_voice_assistant/models/`

## LLM Tool Permissions

`codex_cli`, `gemini_cli`, and `claude_code` can run with broad tool permissions depending on local configuration. The public default config is conservative, but your local `config.local.json` may grant wider permissions.

Before enabling broad permissions such as `danger-full-access`, `approval_policy=never`, `--yolo`, or `bypassPermissions`, make sure the workspace contains no files you would not want the selected LLM tool to access.

## Reporting

If you find a security issue, please open a private report if the hosting platform supports it. Do not include private logs, voice recordings, API tokens, memory files, or full local paths in public issues.
