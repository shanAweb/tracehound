"""Deterministic benchmark scenarios: healthy runs, and runs with one randomly planted fault.

Seeds are split: parameters are tuned on ``dev`` seeds and results are reported on ``test``
seeds, which are never used for tuning. Each group has its own seed range:

- ``healthy``: no fault (measures false alarms)
- ``faulted``: one fault that lasts until the recording ends
- ``ending``: one fault that ends before the recording does (the system recovers)

A fault's kind and service are uniform at random. It starts between 40% and 70% of the way
into the run, at a millisecond offset, so it rarely lines up with a metric interval.
"""

import random
from dataclasses import dataclass
from typing import Literal, get_args

from tracehound.sim import Fault, System

Split = Literal["dev", "test"]
Group = Literal["healthy", "faulted", "ending"]
KINDS = ("latency", "error", "saturation", "regression")
SPLIT_OFFSET: dict[str, int] = {"dev": 0, "test": 1_000_000}
GROUP_OFFSET: dict[str, int] = {"healthy": 0, "faulted": 100_000, "ending": 200_000}


@dataclass(frozen=True)
class Scenario:
    seed: int
    group: Group
    fault: Fault | None
    duration_s: float


def make_scenarios(
    split: Split, group: Group, count: int, *, duration_s: float = 600.0, system: str = "shop"
) -> list[Scenario]:
    """``count`` scenarios of one group. The same arguments always give the same scenarios.

    >>> [s.seed for s in make_scenarios("test", "ending", 2)]
    [1200000, 1200001]
    """
    if split not in SPLIT_OFFSET or group not in get_args(Group) or count < 0:
        raise ValueError(f"bad scenario request: {split!r}, {group!r}, {count}")
    services = System.example(system).topology.service_names
    first = SPLIT_OFFSET[split] + GROUP_OFFSET[group]
    return [_scenario(seed, group, duration_s, services) for seed in range(first, first + count)]


def _scenario(seed: int, group: Group, duration_s: float, services: tuple[str, ...]) -> Scenario:
    if group == "healthy":
        return Scenario(seed, group, None, duration_s)
    # A separate, string-seeded stream: the simulator's own Random(seed) must not see the
    # same numbers that chose the fault. String seeds are stable across Python processes.
    rng = random.Random(f"tracehound-scenario-{seed}")
    kind = rng.choice(KINDS)
    service = rng.choice(services)
    at = round(rng.uniform(0.4, 0.7) * duration_s, 3)
    lasts = round(rng.uniform(0.1, 0.3) * duration_s, 3) if group == "ending" else None
    fault = Fault(kind, service, at=at, duration=lasts)  # type: ignore[arg-type]
    return Scenario(seed, group, fault, duration_s)
