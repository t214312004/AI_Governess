import json
import time
from pathlib import Path

from tools import gemini_auth_probe as probe


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_local_auth_status_accepts_oauth_refresh_token(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    gemini_dir = tmp_path / ".gemini"
    _write_json(
        gemini_dir / "settings.json",
        {"security": {"auth": {"selectedType": probe.AUTH_OAUTH_PERSONAL}}},
    )
    _write_json(
        gemini_dir / "oauth_creds.json",
        {"access_token": "access", "refresh_token": "refresh"},
    )
    _write_json(gemini_dir / "google_accounts.json", {"active": "user@example.com"})

    ok, message = probe._local_auth_status(tmp_path)

    assert ok is True
    assert "refresh token" in message
    assert "user@example.com" in message


def test_local_auth_status_rejects_expired_oauth_without_refresh_token(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    gemini_dir = tmp_path / ".gemini"
    _write_json(
        gemini_dir / "settings.json",
        {"security": {"auth": {"selectedType": probe.AUTH_OAUTH_PERSONAL}}},
    )
    _write_json(
        gemini_dir / "oauth_creds.json",
        {
            "access_token": "access",
            "expiry_date": int(time.time() * 1000) - 1_000,
        },
    )

    ok, message = probe._local_auth_status(tmp_path)

    assert ok is False
    assert "expired" in message


def test_local_auth_status_accepts_api_key_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    ok, message = probe._local_auth_status(tmp_path)

    assert ok is True
    assert "GEMINI_API_KEY" in message


def test_local_auth_status_defers_stored_api_key_to_acp_probe(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    _write_json(
        tmp_path / ".gemini" / "settings.json",
        {"security": {"auth": {"selectedType": probe.AUTH_GEMINI_API_KEY}}},
    )

    ok, message = probe._local_auth_status(tmp_path)

    assert ok is None
    assert "credential storage" in message
