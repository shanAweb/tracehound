"""Parse human-friendly times such as "30s", "10m" or "+4m" into seconds."""

import math
import re

from tracehound._format import NS_PER_S

_SECONDS_PER_UNIT = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
_TIME = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h)\s*$")


def _to_seconds(value: str | float) -> float:
    """A number of seconds, or a string with a unit. Sign and range are checked by callers."""
    if isinstance(value, bool):  # bool is an int subclass; True seconds is surely a bug
        raise TypeError("time must be a number or a string like '10m'")
    if isinstance(value, str):
        match = _TIME.match(value)
        if match is None:
            raise ValueError(f"invalid time {value!r}; use e.g. '500ms', '30s', '10m', '1h'")
        return float(match.group(1)) * _SECONDS_PER_UNIT[match.group(2)]
    seconds = float(value)
    if not math.isfinite(seconds):
        raise ValueError(f"time must be finite, got {value!r}")
    return seconds


def parse_duration(value: str | float) -> float:
    """A positive duration in seconds: ``90``, ``"90s"``, ``"1.5m"``."""
    seconds = _to_seconds(value)
    if not seconds > 0:
        raise ValueError(f"duration must be positive, got {value!r}")
    return seconds


def parse_offset(value: str | float) -> float:
    """A non-negative offset from the start of a run: ``0``, ``240``, ``"4m"`` or ``"+4m"``."""
    if isinstance(value, str) and value.strip().startswith("+"):
        value = value.strip()[1:]
    seconds = _to_seconds(value)
    if seconds < 0:
        raise ValueError(f"offset must be >= 0, got {value!r}")
    return seconds


def seconds_to_ns(seconds: float) -> int:
    """Convert seconds to integer nanoseconds (rounded to the nearest ns)."""
    return round(seconds * NS_PER_S)
