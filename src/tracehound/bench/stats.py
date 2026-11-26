"""Small statistics helpers for reporting benchmark results honestly."""

import math
from collections.abc import Sequence


def wilson(successes: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson score interval for a proportion ``successes / n``.

    Unlike the plain ``p +- z * sqrt(p(1-p)/n)``, it stays inside [0, 1] and is honest at 0/n.

    >>> [round(v, 3) for v in wilson(94, 120)]
    [0.701, 0.848]
    >>> [round(v, 3) for v in wilson(0, 59)]
    [0.0, 0.061]
    """
    if n <= 0 or not 0 <= successes <= n:
        raise ValueError("need 0 <= successes <= n and n > 0")
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def summary(values: Sequence[float]) -> dict[str, float | int]:
    """Count, median, 90th percentile of the absolute value, and the largest absolute value."""
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    absolute = sorted(abs(v) for v in values)
    return {
        "n": len(values),
        "median": round(_quantile(ordered, 0.5), 3),
        "p90_abs": round(_quantile(absolute, 0.9), 3),
        "max_abs": round(absolute[-1], 3),
    }


def _quantile(ordered: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile of sorted values (numpy's default method)."""
    position = q * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)
