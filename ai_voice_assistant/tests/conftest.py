import os

import pytest

os.environ.setdefault("AI_GOVERNESS_DISABLE_LOGGING", "1")

from utils.logger import configure_logging


@pytest.fixture(autouse=True)
def disable_app_logging(monkeypatch):

    monkeypatch.setenv("AI_GOVERNESS_DISABLE_LOGGING", "1")
    configure_logging()
    yield
    monkeypatch.setenv("AI_GOVERNESS_DISABLE_LOGGING", "1")
    configure_logging()

