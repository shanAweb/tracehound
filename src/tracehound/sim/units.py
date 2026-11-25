"""Parse human-friendly durations such as "30s", "10m" or "1h" into seconds."""

import math
import re

from tracehound._format import NS_PER_S

_SECONDS_PER_UNIT = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h)\s*$")


def parse_duration(value: str | float) -> float:
    """Return a positive, finite duration in seconds.

    Accepts a number of seconds (``90``) or a string with a unit (``"90s"``, ``"1.5m"``).
    """
    if isinstance(value, bool):  # bool is an int subclass; True seconds is surely a bug
        raise TypeError("duration must be a number or a string like '10m'")
    if isinstance(value, str):
        match = _DURATION.match(value)
        if match is None:
            raise ValueError(f"invalid duration {value!r}; use e.g. '500ms', '30s', '10m', '1h'")
        seconds = float(match.group(1)) * _SECONDS_PER_UNIT[match.group(2)]
    else:
        seconds = float(value)
    if not (math.isfinite(seconds) and seconds > 0):
        raise ValueError(f"duration must be positive and finite, got {value!r}")
    return seconds


def seconds_to_ns(seconds: float) -> int:
    """Convert seconds to integer nanoseconds (rounded to the nearest ns)."""
    return round(seconds * NS_PER_S)
