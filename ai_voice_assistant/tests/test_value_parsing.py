import pytest

from utils.value_parsing import parse_bool


@pytest.mark.parametrize("value", [False, "false", "FALSE", "0", "no", "off", "n", ""])
def test_parse_bool_false_values(value):
    assert parse_bool(value, default=True) is False


@pytest.mark.parametrize("value", [True, "true", "TRUE", "1", "yes", "on", "y"])
def test_parse_bool_true_values(value):
    assert parse_bool(value, default=False) is True


def test_parse_bool_unknown_and_none_use_default():
    assert parse_bool(None, default=True) is True
    assert parse_bool("maybe", default=False) is False
