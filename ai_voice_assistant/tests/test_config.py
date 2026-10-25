import json

import pytest

from config import Config


@pytest.fixture
def temp_config_file(tmp_path):
    config_file = tmp_path / "test_config.json"
    data = {"test": {"val": 123}}
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return str(config_file)


def test_config_load_save(tmp_path, monkeypatch):
    config_file = tmp_path / "test_config.json"
    monkeypatch.setattr("config.CONFIG_PATH", str(config_file))

    cfg = Config()
    assert cfg.get("test", "val") is None

    cfg.set("a", "b", value="hello")
    cfg.flush()
    assert cfg.get("a", "b") == "hello"

    cfg2 = Config()
    assert cfg2.get("a", "b") == "hello"


def test_config_get_nested():
    cfg = Config()
    cfg._config = {"llm": {"active": "sample_backend"}}
    assert cfg.get("llm", "active") == "sample_backend"
    assert cfg.get("llm", "none") is None
    assert cfg.get("not_exist") is None
    assert cfg.get("llm", "active", default="other") == "sample_backend"
    assert cfg.get("none", default="def") == "def"


def test_config_set_nested(tmp_path, monkeypatch):
    config_file = tmp_path / "test_set.json"
    monkeypatch.setattr("config.CONFIG_PATH", str(config_file))
    cfg = Config()
    cfg.set("x", "y", "z", value=999)
    cfg.flush()
    assert cfg.get("x", "y", "z") == 999

    cfg.set("x", "y", "w", value=111)
    cfg.flush()
    assert cfg.get("x", "y", "w") == 111


def test_config_set_same_value_does_not_mark_dirty(tmp_path, monkeypatch, mocker):
    config_file = tmp_path / "same_value.json"
    monkeypatch.setattr("config.CONFIG_PATH", str(config_file))
    cfg = Config()
    cfg.set("a", "b", value="hello")
    cfg.flush()

    schedule_save = mocker.spy(cfg, "_schedule_save")
    changed = cfg.set("a", "b", value="hello")

    assert changed is False
    assert cfg._dirty is False
    schedule_save.assert_not_called()


def test_config_flush_skips_save_when_clean(tmp_path, monkeypatch, mocker):
    config_file = tmp_path / "clean_flush.json"
    monkeypatch.setattr("config.CONFIG_PATH", str(config_file))
    cfg = Config()

    save = mocker.spy(cfg, "save")
    cfg.flush()

    save.assert_not_called()


def test_config_load_error(tmp_path, monkeypatch):
    default_file = tmp_path / "defaults.json"
    default_file.write_text('{"audio": {"input_sample_rate": 16000}}', encoding="utf-8")
    config_file = tmp_path / "bad.json"
    with open(config_file, "w", encoding="utf-8") as f:
        f.write("{ invalid json }")
    monkeypatch.setattr("config.CONFIG_PATH", str(config_file))
    cfg = Config(default_path=str(default_file))
    assert cfg.get("audio", "input_sample_rate") == 16000
    assert cfg.loaded_paths == [str(default_file)]


def test_config_non_object_private_file_keeps_defaults(tmp_path):
    default_file = tmp_path / "defaults.json"
    default_file.write_text('{"heartbeat": {"enabled": true}}', encoding="utf-8")
    config_file = tmp_path / "local.json"
    config_file.write_text("[]", encoding="utf-8")

    cfg = Config(default_path=str(default_file), config_path=str(config_file))

    assert cfg.get("heartbeat", "enabled") is True
    assert cfg.loaded_paths == [str(default_file)]


def test_config_save_persists_sparse_overrides_atomically(tmp_path, mocker):
    default_file = tmp_path / "defaults.json"
    default_file.write_text(
        '{"audio": {"input_sample_rate": 16000, "output_sample_rate": 24000}}',
        encoding="utf-8",
    )
    config_file = tmp_path / "local.json"
    cfg = Config(default_path=str(default_file), config_path=str(config_file))
    replace = mocker.spy(__import__("config").os, "replace")

    cfg.set("audio", "input_sample_rate", value=48000)
    cfg.flush()

    assert json.loads(config_file.read_text(encoding="utf-8")) == {
        "audio": {"input_sample_rate": 48000}
    }
    assert cfg.get("audio", "output_sample_rate") == 24000
    replace.assert_called_once()


def test_config_save_error(tmp_path, monkeypatch):
    monkeypatch.setattr("config.CONFIG_PATH", "/non_existent_dir/file.json")
    cfg = Config()
    cfg._config = {"test": 1}
    cfg.save()


@pytest.fixture
def legacy_antigravity_config(tmp_path):
    defaults = tmp_path / "defaults.json"
    local = tmp_path / "synthetic-private.json"
    defaults.write_text(json.dumps({
        "llm": {"response_timeout_seconds": 360,
                "antigravity_cli": {"startup_timeout_seconds": 90, "request_timeout_seconds": 120}},
    }), encoding="utf-8")

    def load(duration="5m0s", *, global_timeout=...):
        private = {
            "unknown_private": {"nested": ["保留", {"custom": True}]},
            "llm": {
                "active_backend": "antigravity_cli",
                "provider_unknown": {"keep": "synthetic"},
                "antigravity_cli": {"print_timeout": duration, "model": "gemini-4-argon-low",
                                    "request_timeout_seconds": 121, "custom_private": [1, 2]},
                "other_backend": {"print_timeout": "keep-this-unrelated-key"},
            },
        }
        if global_timeout is not ...:
            private["llm"]["response_timeout_seconds"] = global_timeout
        local.write_text(json.dumps(private, ensure_ascii=False), encoding="utf-8")
        before = local.read_bytes()
        return Config(str(defaults), str(local)), local, private, before

    return load


@pytest.mark.parametrize(("duration", "seconds"), [
    ("5m0s", 300), ("1h2m3.5s", 3723.5), ("250ms", .25),
    (".5s", .5), ("+90s", 90), (" 2m ", 120), ("500µs", .0005),
])
def test_antigravity_duration_migrates_to_global_turn_timeout_only(legacy_antigravity_config, duration, seconds):
    cfg, local, private, before = legacy_antigravity_config(duration)

    assert cfg.get("llm", "response_timeout_seconds") == pytest.approx(seconds)
    assert cfg.get("llm", "antigravity_cli", "print_timeout") is None
    assert cfg.get("llm", "antigravity_cli", "request_timeout_seconds") == 121
    assert cfg.get("llm", "antigravity_cli", "startup_timeout_seconds") == 90
    assert cfg.get("llm", "other_backend", "print_timeout") == "keep-this-unrelated-key"
    assert cfg.snapshot()["unknown_private"] == private["unknown_private"]
    assert local.read_bytes() == before
    assert cfg._save_timer is None


@pytest.mark.parametrize("timeout", [15, 0, None, "explicit-user-value"])
def test_explicit_private_global_timeout_wins_over_legacy_duration(legacy_antigravity_config, timeout):
    cfg, local, _private, before = legacy_antigravity_config("5m0s", global_timeout=timeout)

    assert cfg.get("llm", "response_timeout_seconds") == timeout
    assert cfg.get("llm", "antigravity_cli", "print_timeout") is None
    assert local.read_bytes() == before


@pytest.mark.parametrize("duration", [
    None, False, 300, "", "0s", "-1m", "1m trailing-junk", "30", "inf",
    "1e309s", "9" * 400 + "s", "synthetic-private-invalid-value",
])
def test_invalid_duration_keeps_global_default_without_losing_private_keys(
    legacy_antigravity_config, mocker, duration,
):
    warning = mocker.patch("config.logger.warning")
    cfg, local, private, before = legacy_antigravity_config(duration)

    assert cfg.get("llm", "response_timeout_seconds") == 360
    assert cfg.get("llm", "antigravity_cli", "print_timeout") is None
    assert cfg.get("llm", "antigravity_cli", "custom_private") == [1, 2]
    assert cfg.get("unknown_private") == private["unknown_private"]
    assert local.read_bytes() == before
    assert len(warning.call_args_list) == 1
    assert "synthetic-private-invalid-value" not in str(warning.call_args)


@pytest.mark.parametrize("save_method", ["save", "flush", "apply_snapshot"])
def test_normal_save_persists_migration_once_and_preserves_every_other_private_key(
    legacy_antigravity_config, save_method,
):
    cfg, local, private, before = legacy_antigravity_config("5m0s")
    assert local.read_bytes() == before

    if save_method == "apply_snapshot":
        assert cfg.apply_snapshot(cfg.snapshot()) is True
    else:
        getattr(cfg, save_method)()

    expected = json.loads(json.dumps(private))
    expected["llm"]["antigravity_cli"].pop("print_timeout")
    expected["llm"]["response_timeout_seconds"] = 300
    assert json.loads(local.read_text(encoding="utf-8")) == expected
    reloaded = Config(cfg.default_path, str(local))
    assert reloaded.snapshot() == cfg.snapshot()
    assert reloaded._dirty is False
    assert reloaded.apply_snapshot(reloaded.snapshot()) is False


def test_invalid_duration_is_removed_on_save_without_materializing_defaults(legacy_antigravity_config):
    cfg, local, private, _before = legacy_antigravity_config("bad-duration")
    cfg.save()

    private["llm"]["antigravity_cli"].pop("print_timeout")
    assert json.loads(local.read_text(encoding="utf-8")) == private
    assert "response_timeout_seconds" not in private["llm"]


@pytest.mark.parametrize("llm", [None, [], "custom-private-value", {"antigravity_cli": None}])
def test_unrelated_private_config_shapes_are_preserved(tmp_path, llm):
    default = tmp_path / "defaults.json"
    local = tmp_path / "synthetic-private.json"
    default.write_text("{}", encoding="utf-8")
    private = {"llm": llm, "unrecognized": {"keep": True}}
    local.write_text(json.dumps(private), encoding="utf-8")

    cfg = Config(str(default), str(local))

    assert cfg.snapshot() == private
    assert cfg._dirty is False

