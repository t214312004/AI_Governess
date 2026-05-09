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
    cfg._config = {"llm": {"active": "gemini"}}
    assert cfg.get("llm", "active") == "gemini"
    assert cfg.get("llm", "none") is None
    assert cfg.get("not_exist") is None
    assert cfg.get("llm", "active", default="other") == "gemini"
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
    config_file = tmp_path / "bad.json"
    with open(config_file, "w", encoding="utf-8") as f:
        f.write("{ invalid json }")
    monkeypatch.setattr("config.CONFIG_PATH", str(config_file))
    cfg = Config()
    assert cfg._config == {}


def test_config_save_error(tmp_path, monkeypatch):
    monkeypatch.setattr("config.CONFIG_PATH", "/non_existent_dir/file.json")
    cfg = Config()
    cfg._config = {"test": 1}
    cfg.save()

