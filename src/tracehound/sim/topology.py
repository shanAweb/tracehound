"""Service topology: which services exist, how fast and reliable they are, and whom they call."""

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Service:
    """One microservice.

    Its own processing time (excluding callees) is lognormal around ``base_ms``, so
    ``base_ms`` is the median and ``jitter`` the lognormal sigma. ``error_rate`` is the
    chance that a request fails inside this service itself.
    """

    name: str
    operation: str
    base_ms: float
    jitter: float = 0.25
    error_rate: float = 0.001

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("service name must be non-empty")
        if not self.base_ms > 0:
            raise ValueError(f"{self.name}: base_ms must be > 0")
        if not self.jitter >= 0:
            raise ValueError(f"{self.name}: jitter must be >= 0")
        if not 0.0 <= self.error_rate <= 1.0:
            raise ValueError(f"{self.name}: error_rate must be in [0, 1]")


@dataclass(frozen=True)
class Call:
    """``caller`` calls ``callee`` for a share (``probability``) of its requests.

    If the callee takes longer than ``timeout_ms``, the caller gives up and fails.
    """

    caller: str
    callee: str
    probability: float = 1.0
    timeout_ms: float = 1000.0

    def __post_init__(self) -> None:
        if self.caller == self.callee:
            raise ValueError(f"{self.caller} cannot call itself")
        if not 0.0 < self.probability <= 1.0:
            raise ValueError(f"{self.caller}->{self.callee}: probability must be in (0, 1]")
        if not self.timeout_ms > 0:
            raise ValueError(f"{self.caller}->{self.callee}: timeout_ms must be > 0")


class Topology:
    """A validated set of services and calls: acyclic, one entry, everything reachable.

    Calls keep the order they were given in, because a service makes its calls one after
    another in that order.
    """

    def __init__(
        self, name: str, services: Iterable[Service], calls: Iterable[Call], entry: str
    ) -> None:
        self.name = name
        self.services: dict[str, Service] = {}
        for service in services:
            if service.name in self.services:
                raise ValueError(f"duplicate service {service.name!r}")
            self.services[service.name] = service
        if entry not in self.services:
            raise ValueError(f"entry service {entry!r} is not defined")
        self.entry = entry

        calls_by_caller: dict[str, list[Call]] = {name: [] for name in self.services}
        for call in calls:
            for end in (call.caller, call.callee):
                if end not in self.services:
                    raise ValueError(f"call {call.caller}->{call.callee}: unknown service {end!r}")
            calls_by_caller[call.caller].append(call)
        self._calls = {caller: tuple(cs) for caller, cs in calls_by_caller.items()}
        self._validate_graph()

    @property
    def service_names(self) -> tuple[str, ...]:
        """All service names, sorted."""
        return tuple(sorted(self.services))

    def calls_from(self, caller: str) -> tuple[Call, ...]:
        """The calls ``caller`` makes, in the order it makes them."""
        return self._calls[caller]

    def edges(self) -> list[tuple[str, str]]:
        """Sorted ``(caller, callee)`` pairs: the true call graph."""
        return sorted((c.caller, c.callee) for calls in self._calls.values() for c in calls)

    def _validate_graph(self) -> None:
        if any(callee == self.entry for _, callee in self.edges()):
            raise ValueError(f"entry service {self.entry!r} must not be called by others")
        # Kahn's algorithm: if a topological order cannot cover every node, there is a cycle.
        indegree = {name: 0 for name in self.services}
        for _, callee in self.edges():
            indegree[callee] += 1
        ready = deque(sorted(name for name, d in indegree.items() if d == 0))
        ordered = 0
        while ready:
            node = ready.popleft()
            ordered += 1
            for call in self._calls[node]:
                indegree[call.callee] -= 1
                if indegree[call.callee] == 0:
                    ready.append(call.callee)
        if ordered != len(self.services):
            raise ValueError("topology has a call cycle")
        unreachable = set(self.services) - self._reachable_from_entry()
        if unreachable:
            raise ValueError(f"services not reachable from {self.entry!r}: {sorted(unreachable)}")

    def _reachable_from_entry(self) -> set[str]:
        seen, stack = {self.entry}, [self.entry]
        while stack:
            for call in self._calls[stack.pop()]:
                if call.callee not in seen:
                    seen.add(call.callee)
                    stack.append(call.callee)
        return seen
