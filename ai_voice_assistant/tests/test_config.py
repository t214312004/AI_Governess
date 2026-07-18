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

