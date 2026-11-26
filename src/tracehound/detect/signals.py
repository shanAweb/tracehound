"""What counts as "worse" for each metric, and how large a change must be to matter."""

from dataclasses import dataclass
from typing import Literal

from tracehound import _format as fmt

Direction = Literal["up", "down"]

# The direction in which each standard metric gets worse. Any other metric is checked both ways.
BAD_DIRECTION: dict[str, Direction] = {
    fmt.ERROR_RATE: "up",
    fmt.LATENCY_P50: "up",
    fmt.LATENCY_P95: "up",
    fmt.LATENCY_P99: "up",
    fmt.THROUGHPUT: "down",
    fmt.UTILIZATION: "up",
}


@dataclass(frozen=True)
class MinEffect:
    """The smallest change worth reporting: ``relative`` to the baseline and/or ``absolute``.

    A change must pass both. Statistics decide whether a change is real; this decides whether
    it is big enough to matter (a 1% latency rise can be real and still irrelevant).
    """

    relative: float = 0.0
    absolute: float = 0.0


MIN_EFFECT: dict[str, MinEffect] = {
    fmt.ERROR_RATE: MinEffect(absolute=0.01),  # +1 percentage point
    fmt.LATENCY_P50: MinEffect(relative=0.10),  # +10%
    fmt.LATENCY_P95: MinEffect(relative=0.10),
    fmt.LATENCY_P99: MinEffect(relative=0.10),
    fmt.THROUGHPUT: MinEffect(relative=0.20),  # -20%
    fmt.UTILIZATION: MinEffect(absolute=0.05),  # +5 percentage points of capacity
}
DEFAULT_MIN_EFFECT = MinEffect(relative=0.10)


def bad_directions(metric: str) -> tuple[Direction, ...]:
    """The directions to check: the bad one for standard metrics, both for anything else.

    >>> bad_directions("throughput_rps"), bad_directions("db_connections")
    (('down',), ('up', 'down'))
    """
    known = BAD_DIRECTION.get(metric)
    return (known,) if known else ("up", "down")


def is_material(metric: str, baseline: float, observed: float, direction: Direction) -> bool:
    """Whether moving from ``baseline`` to ``observed`` is a big enough change for ``metric``."""
    change = observed - baseline if direction == "up" else baseline - observed
    effect = MIN_EFFECT.get(metric, DEFAULT_MIN_EFFECT)
    return change > 0 and change >= effect.absolute and change >= effect.relative * abs(baseline)
