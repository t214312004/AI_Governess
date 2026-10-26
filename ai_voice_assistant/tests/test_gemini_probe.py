"""Research tooling cannot accidentally export generated music into public files."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def probe(tmp_path,monkeypatch):
    path=Path(__file__).resolve().parents[2]/'scripts/gemini_api_capability_probe.py'
    spec=importlib.util.spec_from_file_location('gemini_capability_probe_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setattr(module,'APP',tmp_path/'ai_voice_assistant')
    return module


def test_probe_accepts_only_ignored_output_roots(probe):
    assert probe.validate_output_directory(probe.ROOT/'tool_payloads/run')==probe.ROOT/'tool_payloads/run'
    assert probe.validate_output_directory(probe.APP/'tool_payloads/run')==probe.APP/'tool_payloads/run'
    for path in (probe.ROOT/'docs/music',probe.ROOT/'tool_payloads-public',probe.ROOT/'tool_payloads/../public'):
        with pytest.raises(ValueError):probe.validate_output_directory(path)


def test_probe_child_environment_avoids_inherited_debug_and_other_credentials(probe,monkeypatch):
    for name in ('DEBUG','GEMINI_DEBUG','GOOGLE_API_KEY','GEMINI_ACCESS_TOKEN'):
        monkeypatch.setenv(name,'unrelated')
    env=probe.child_env('chosen-test-key')
    assert env['GEMINI_API_KEY']=='chosen-test-key'
    assert not {'DEBUG','GEMINI_DEBUG','GOOGLE_API_KEY','GEMINI_ACCESS_TOKEN'}&env.keys()
