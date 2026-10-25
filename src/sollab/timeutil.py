"""UTC timestamps for venue payloads and local fetch times."""

from datetime import datetime, timezone
from decimal import Decimal


def parse_timestamp(value: object) -> datetime:
    """Parse a venue timestamp into timezone-aware UTC.

    Unix seconds and ISO-8601 are accepted. A trailing Z is UTC. Fractional
    seconds longer than microseconds are truncated, never rounded up, so a
    nanosecond venue stamp cannot move into the next microsecond.
    Naive ISO strings are treated as UTC.
    """
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return datetime.fromtimestamp(int(value), timezone.utc)
        return datetime.fromtimestamp(float(value), timezone.utc)
    if isinstance(value, int) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, float):
        return datetime.fromtimestamp(value, timezone.utc)
    if not isinstance(value, str):
        raise TypeError(f"unsupported timestamp type: {type(value).__name__}")

    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    if "." in text:
        head, rest = text.split(".", 1)
        plus = rest.rfind("+")
        minus = rest.rfind("-")
        idx = max(plus, minus)
        if idx == -1:
            frac, tz = rest, ""
        else:
            frac, tz = rest[:idx], rest[idx:]
        digits = "".join(ch for ch in frac if ch.isdigit())
        text = f"{head}.{(digits + '000000')[:6]}{tz}"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    """Format UTC as ISO-8601 with a Z suffix."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    utc = value.astimezone(timezone.utc)
    base = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if utc.microsecond:
        return f"{base}.{utc.microsecond:06d}Z"
    return f"{base}Z"
