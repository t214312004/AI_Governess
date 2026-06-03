EDGE_TTS_RATE_MIN_PERCENT = -30
EDGE_TTS_RATE_MAX_PERCENT = 30
EDGE_TTS_RATE_STEPS = EDGE_TTS_RATE_MAX_PERCENT - EDGE_TTS_RATE_MIN_PERCENT


def format_edge_tts_rate_percent(value: float | int) -> str:
    rate = int(float(value))
    sign = "+" if rate >= 0 else ""
    return f"{sign}{rate}%"


def clamp_edge_tts_rate_percent(value: float | int) -> int:
    rate = int(float(value))
    return max(EDGE_TTS_RATE_MIN_PERCENT, min(EDGE_TTS_RATE_MAX_PERCENT, rate))


def normalize_edge_tts_rate(value: str | float | int | None, default: str = "+0%") -> str:
    if value is None:
        value = default

    try:
        numeric_value = float(str(value).replace("%", "").replace("+", ""))
    except (TypeError, ValueError):
        numeric_value = 0.0

    return format_edge_tts_rate_percent(clamp_edge_tts_rate_percent(numeric_value))
