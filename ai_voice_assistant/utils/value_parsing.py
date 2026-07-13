"""Side-effect-free parsing helpers for values loaded from JSON or environment-like sources."""

_TRUE_VALUES = {"1", "true", "yes", "on", "y"}
_FALSE_VALUES = {"0", "false", "no", "off", "n", ""}


def parse_bool(value, *, default: bool = False) -> bool:
    """Parse common serialized booleans without treating ``"false"`` as truthy."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
        return default
    return bool(value)
