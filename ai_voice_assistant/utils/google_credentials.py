"""Explicit, atomic updates to the app's private Google credential."""
import os


def save_google_api_key(config, value: str) -> None:
    key = value.strip()
    if key and any(char.isspace() for char in key):
        raise ValueError("API key 不可包含空白或換行")
    # Persist only this credential, never the startup editor's unrelated draft.
    snapshot = config.snapshot()
    snapshot.setdefault("gemini", {})["api_key"] = key
    config.apply_snapshot(snapshot)


def google_key_status(settings: dict) -> str:
    section = settings.get("gemini", {})
    if str(section.get("api_key") or "").strip():
        return "已儲存於本機 private config"
    env_name = section.get("api_key_env", "GEMINI_API_KEY")
    if os.environ.get(env_name, "").strip():
        return f"使用環境變數 {env_name}；刪除本機 key 不會刪除此環境變數"
    return "尚未設定 Google API key"
