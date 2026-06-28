"""Parse clock annotations from PGN comments ([%clk], [%emt])."""

from datetime import timedelta


def _parse_hms(value):
    """Parse H:MM:SS or M:SS into seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, timedelta):
        return value.total_seconds()
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(text)
    except (TypeError, ValueError):
        return None


def extract_mainline_clocks(game):
    """
    Return one dict per mainline move, aligned with game.mainline_moves().
    Each entry: clock_before, clock_after, emt_seconds.
    """
    entries = []
    clock_before = None

    for node in game.mainline():
        clock_after = node.clock() if callable(getattr(node, "clock", None)) else getattr(node, "clock", None)
        emt = node.emt() if callable(getattr(node, "emt", None)) else getattr(node, "emt", None)

        clock_after_sec = _parse_hms(clock_after)
        emt_sec = _parse_hms(emt)

        entries.append({
            "clock_before_seconds": clock_before,
            "clock_after_seconds": clock_after_sec,
            "emt_seconds": emt_sec,
        })
        clock_before = clock_after_sec

    return entries


def parse_time_control(headers):
    """Parse TimeControl header into initial seconds if possible."""
    tc = (headers or {}).get("TimeControl", "")
    if not tc or tc == "-":
        return None
    # Common: "600" (10 min) or "600+5" or "600+0"
    base = tc.split("+")[0].split("/")[0]
    try:
        return int(base)
    except ValueError:
        return None


def is_time_pressure(clock_before_seconds, emt_seconds, avg_emt=None, threshold=30):
    """True when the player likely blundered under time pressure."""
    if clock_before_seconds is not None and clock_before_seconds <= threshold:
        return True
    if emt_seconds is not None and avg_emt and emt_seconds >= avg_emt * 2.5 and clock_before_seconds is not None:
        if clock_before_seconds <= 120:
            return True
    return False
