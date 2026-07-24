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

`logs/llm_io-YYYY-MM-DD.log` contains full LLM prompts and responses in plaintext by default and is retained for five days. Runtime files are excluded from Git, but Git exclusion does not mean data is never transmitted: Groq STT, Edge TTS, cloud-backed LLM CLIs, and enabled web-search tools send the data needed for each request to their respective services.

## LLM Tool Permissions

`antigravity_cli`, `opencode_cli`, `grok_cli`, `codex_cli`, and `claude_code` can run with broad tool permissions. The public defaults are not a sandbox boundary: Antigravity uses `--dangerously-skip-permissions`, OpenCode defaults to `permission_mode=yolo` with auto-approval and web search, Grok defaults to allow-once auto-approval with web search, and Codex defaults to `danger-full-access` with `approval_policy=never`.

Before using broad permissions such as `danger-full-access`, `approval_policy=never`, `--yolo`, `bypassPermissions`, or the public defaults described above, make sure the workspace contains no files you would not want the selected LLM tool to access.

## Reporting

If you find a security issue, please open a private report if the hosting platform supports it. Do not include private logs, voice recordings, API tokens, memory files, or full local paths in public issues.
