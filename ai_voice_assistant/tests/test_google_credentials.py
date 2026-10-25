import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from config import Config
from utils.google_credentials import google_key_status, save_google_api_key


def make_config(tmp_path):
    defaults = tmp_path / "default.json"
    defaults.write_text('{"gemini":{"api_key":"","api_key_env":"TEST_GOOGLE_KEY"}}', encoding="utf-8")
    local = tmp_path / "local.json"
    local.write_text('{"private_custom":{"preserved":true}}', encoding="utf-8")
    return Config(str(defaults), str(local))


def test_google_key_save_delete_is_immediate_and_preserves_other_settings(tmp_path):
    cfg = make_config(tmp_path)
    save_google_api_key(cfg, " opaque-test-key ")
    assert Config(cfg.default_path, cfg.config_path).get("gemini", "api_key") == "opaque-test-key"
    save_google_api_key(cfg, "")
    saved = json.loads(Path(cfg.config_path).read_text(encoding="utf-8"))
    assert saved["gemini"]["api_key"] == ""
    assert saved["private_custom"] == {"preserved": True}
    assert "opaque-test-key" not in Path(cfg.config_path).read_text(encoding="utf-8")


def test_google_key_failed_write_keeps_old_key_and_file(tmp_path):
    cfg = make_config(tmp_path)
    save_google_api_key(cfg, "old-test-key")
    before = Path(cfg.config_path).read_bytes()
    with patch("config.os.replace", side_effect=OSError("write error")):
        with pytest.raises(OSError):
            save_google_api_key(cfg, "")
    assert cfg.get("gemini", "api_key") == "old-test-key"
    assert Path(cfg.config_path).read_bytes() == before


def test_key_status_does_not_display_secrets_or_delete_environment(tmp_path, monkeypatch):
    cfg = make_config(tmp_path)
    monkeypatch.setenv("TEST_GOOGLE_KEY", "env-test-secret")
    assert "環境變數 TEST_GOOGLE_KEY" in google_key_status(cfg.snapshot())
    save_google_api_key(cfg, "stored-test-secret")
    assert "secret" not in google_key_status(cfg.snapshot())
    save_google_api_key(cfg, "")
    assert os.environ["TEST_GOOGLE_KEY"] == "env-test-secret"
    with pytest.raises(ValueError, match="不可包含空白"):
        save_google_api_key(cfg, "bad key")


@pytest.mark.skipif(os.environ.get("AI_GOVERNESS_NATIVE_TESTS") != "1",
    reason="Opt-in native Tk UI test")
def test_startup_key_editor_saves_deletes_and_survives_page_changes(tmp_path):
    import customtkinter as ctk
    from ui.startup import StartupView
    from ui.google_credentials import GoogleCredentialsEditor
    from config import config

    default = Path(config.default_path)
    cfg = Config(str(default), str(tmp_path / "private.json"))
    root = ctk.CTk()
    root.withdraw()
    view = StartupView(root, cfg.snapshot(), lambda *a: None,
        save_google_key=lambda key: save_google_api_key(cfg, key))
    view.pack(fill="both", expand=True)
    try:
        view.navigate(1)
        root.update()
        def find_editor(owner):
            if isinstance(owner, GoogleCredentialsEditor):
                return owner
            for child in owner.winfo_children():
                found = find_editor(child)
                if found:
                    return found
        editor = find_editor(view)
        assert editor.key.get() == ""
        editor.key.set("opaque-ui-test-key")
        editor.save()
        assert cfg.get("gemini", "api_key") == "opaque-ui-test-key"
        assert editor.key.get() == "" and editor.entry.cget("show") == "•"
        view.navigate(3)
        view.navigate(1)
        editor = find_editor(view)
        editor.delete()
        assert cfg.get("gemini", "api_key") == ""
        view.navigate(4)
        assert view.settings["gemini"]["api_key"] == ""
        assert "opaque-ui-test-key" not in Path(cfg.config_path).read_text(encoding="utf-8")
    finally:
        view.destroy()
        for job in root.tk.call('after', 'info'):
            root.after_cancel(job)
        root.destroy()
