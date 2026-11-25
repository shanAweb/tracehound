"""Faults that can be planted in a simulated run, and how they change requests.

====================  =====================================  =======  ==========================
kind                  ``strength`` means                     default  ground_truth.json param
====================  =====================================  =======  ==========================
``"latency"``         extra own processing time (ms)         850      ``added_ms``
``"error"``           chance a request fails in the service  0.3      ``error_rate``
``"saturation"``      seconds until the pool is exhausted    300      ``time_to_exhaustion_s``
``"regression"``      multiplier on own processing time      1.3      ``latency_factor``
====================  =====================================  =======  ==========================

Saturation models a leak: the share of the service's pool held by leaked resources grows
linearly from 0 at onset to 1 after ``strength`` seconds. Until then requests queue, so own
time is multiplied by ``1 / (1 - leaked)`` (capped at 20x). After that the pool is exhausted:
every request is rejected after its normal own time, with no queueing and no calls.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, NamedTuple, get_args

from tracehound._format import NS_PER_S, JsonValue
from tracehound.sim.topology import Topology
from tracehound.sim.units import parse_duration, parse_offset, seconds_to_ns

FaultKind = Literal["latency", "error", "saturation", "regression"]
_PARAM = {  # kind -> (parameter name in ground_truth.json, default strength)
    "latency": ("added_ms", 850.0),
    "error": ("error_rate", 0.3),
    "saturation": ("time_to_exhaustion_s", 300.0),
    "regression": ("latency_factor", 1.3),
}
MAX_QUEUE_LEAK = 0.95  # caps the saturation slow-down at 1 / (1 - 0.95) = 20x


@dataclass(frozen=True)
class Fault:
    """A fault in ``service``, starting ``at`` after the run starts.

    It lasts for ``duration``, or until the run ends if ``duration`` is None.
    """

    kind: FaultKind
    service: str
    at: str | float = 0.0
    duration: str | float | None = None
    strength: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in get_args(FaultKind):
            raise ValueError(f"unknown fault kind {self.kind!r}; use one of {get_args(FaultKind)}")
        parse_offset(self.at)
        if self.duration is not None:
            parse_duration(self.duration)
        s = self.value
        valid = {
            "latency": s > 0,
            "error": 0 < s <= 1,
            "saturation": s > 0,
            "regression": s > 1,
        }[self.kind]
        if not valid:
            raise ValueError(f"{self.kind} fault: invalid strength {s!r}")

    @property
    def value(self) -> float:
        """The strength, or the kind's default if none was given."""
        return _PARAM[self.kind][1] if self.strength is None else float(self.strength)

    @property
    def param_name(self) -> str:
        return _PARAM[self.kind][0]


class Effect(NamedTuple):
    """How active faults change one service's handling of a request."""

    extra_ms: float = 0.0
    latency_factor: float = 1.0
    error_rate: float = 0.0
    exhausted: bool = False


NO_EFFECT = Effect()


class _Window(NamedTuple):
    fault: Fault
    start_ns: int
    end_ns: int


class FaultPlan:
    """Faults resolved to absolute time windows for one run."""

    def __init__(
        self, faults: Sequence[Fault], topology: Topology, start_ns: int, end_ns: int
    ) -> None:
        self._windows: dict[str, list[_Window]] = {}
        for fault in faults:
            if fault.service not in topology.services:
                raise ValueError(f"fault targets unknown service {fault.service!r}")
            begin = start_ns + seconds_to_ns(parse_offset(fault.at))
            if begin >= end_ns:
                raise ValueError(f"fault at {fault.at!r} starts after the run ends")
            stop = end_ns
            if fault.duration is not None:
                stop = min(end_ns, begin + seconds_to_ns(parse_duration(fault.duration)))
            self._windows.setdefault(fault.service, []).append(_Window(fault, begin, stop))

    def effect(self, service: str, t_ns: int) -> Effect:
        """The combined effect of every fault active in ``service`` at ``t_ns``."""
        windows = self._windows.get(service)
        if not windows:
            return NO_EFFECT
        extra_ms, factor, error_rate, exhausted = 0.0, 1.0, 0.0, False
        for w in windows:
            if not w.start_ns <= t_ns < w.end_ns:
                continue
            kind, s = w.fault.kind, w.fault.value
            if kind == "latency":
                extra_ms += s
            elif kind == "error":
                error_rate = max(error_rate, s)
            elif kind == "regression":
                factor *= s
            else:  # saturation: queue while the pool fills, reject at once when it is full
                leaked = _leaked(w, t_ns)
                if leaked >= 1.0:
                    exhausted = True
                else:
                    factor /= 1.0 - min(leaked, MAX_QUEUE_LEAK)
        return Effect(extra_ms, factor, error_rate, exhausted)

    def leaked_share(self, service: str, t_ns: int) -> float:
        """Share of ``service``'s pool (0 to 1) held by leaks at ``t_ns``; feeds utilization."""
        shares = [
            min(_leaked(w, t_ns), 1.0)
            for w in self._windows.get(service, [])
            if w.fault.kind == "saturation" and w.start_ns <= t_ns < w.end_ns
        ]
        return min(sum(shares), 1.0)

    def ground_truth(self) -> list[JsonValue]:
        """The planted faults as JSON records, sorted by onset, then service and kind."""
        windows = sorted(
            (w for ws in self._windows.values() for w in ws),
            key=lambda w: (w.start_ns, w.fault.service, w.fault.kind),
        )
        return [
            {
                "kind": w.fault.kind,
                "service": w.fault.service,
                "start_ns": w.start_ns,
                "end_ns": w.end_ns,
                "params": {w.fault.param_name: w.fault.value},
            }
            for w in windows
        ]


def _leaked(window: _Window, t_ns: int) -> float:
    return (t_ns - window.start_ns) / (window.fault.value * NS_PER_S)
