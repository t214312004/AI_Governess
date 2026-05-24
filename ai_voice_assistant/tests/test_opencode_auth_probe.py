import pytest
from unittest.mock import AsyncMock

from tools import opencode_auth_probe


def test_opencode_auth_probe_executable_missing(mocker, capsys):
    mocker.patch.object(opencode_auth_probe, "_find_opencode", return_value=None)

    assert opencode_auth_probe.main() == 127

    captured = capsys.readouterr()
    assert "OpenCode CLI was not found" in captured.err


def test_opencode_auth_probe_success(mocker, capsys):
    mocker.patch.object(opencode_auth_probe, "_find_opencode", return_value="opencode.cmd")
    mocker.patch.object(opencode_auth_probe, "_run_probe", new=AsyncMock(return_value=(True, "ready")))

    assert opencode_auth_probe.main() == 0

    captured = capsys.readouterr()
    assert "[OK] ready." in captured.out


def test_opencode_auth_probe_failure(mocker, capsys):
    mocker.patch.object(opencode_auth_probe, "_find_opencode", return_value="opencode.cmd")
    mocker.patch.object(opencode_auth_probe, "_run_probe", new=AsyncMock(return_value=(False, "bad auth")))

    assert opencode_auth_probe.main() == 1

    captured = capsys.readouterr()
    assert "OpenCode ACP check failed" in captured.err


@pytest.mark.asyncio
async def test_opencode_auth_probe_uses_web_search_config(mocker):
    captured_kwargs = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        async def ensure_ready(self):
            return True

        async def aclose(self):
            return None

    mocker.patch.object(
        opencode_auth_probe.config,
        "get",
        return_value={"enable_web_search": True},
    )
    mocker.patch.object(opencode_auth_probe, "OpenCodeCLIClient", FakeClient)

    ok, message = await opencode_auth_probe._run_probe(1.0)

    assert ok is True
    assert "succeeded" in message
    assert captured_kwargs["enable_web_search"] is True
