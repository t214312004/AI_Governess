# Whiteboard State

Runtime whiteboard state and generated display assets live here.

Only this placeholder file should be committed. `active.json`, `.whiteboard.lock`,
`html-usage.json`, `html-usage.lock`, `assets/`, and the HTML whiteboard Edge profile under `html_profile/` are local
runtime state and must stay untracked.

Closing the session preserves active content and its hidden state; explicitly closing the board clears
it. Hidden HTML is unloaded, and restoring it reloads the page with the same local
origin/profile. Only app data saved in localStorage survives reload. HTML usage
persists across restarts and resets at midnight in Asia/Taipei; the default daily
limit is 30 minutes. Markdown and images do not consume HTML time.

See `docs/html_whiteboard.md` in the repository root for the interactive HTML
whiteboard architecture, security boundary, storage behavior, and reset steps.
