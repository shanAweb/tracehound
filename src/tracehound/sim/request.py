"""Simulate one request as it travels through the topology, producing one span per service.

Model of a single service handling a request:

1. It spends its own processing time: lognormal around ``base_ms``, half before its calls
   and half after them.
2. It may fail by itself with probability ``error_rate``. A failed service makes no calls.
3. Otherwise it calls its callees one after another, in topology order:
   - if a callee runs past the call's ``timeout_ms``, the caller stops waiting, fails, and
     makes no further calls. The callee's own span still runs to completion, as in real
     systems where the server never learns that the client gave up.
   - if a callee fails, the caller fails too and makes no further calls (fail fast).

Active faults (see ``faults.py``) are looked up when a service *starts* handling a request:
they stretch its own time ``(base_ms * latency_factor + extra_ms)``, raise its error rate, or,
when its pool is exhausted, make it fail at once.
"""

import random
from typing import NamedTuple

from tracehound._format import NS_PER_MS
from tracehound.sim.faults import NO_EFFECT, FaultPlan
from tracehound.sim.topology import Topology


class SpanRecord(NamedTuple):
    """One service's work on one request. IDs are empty strings for unsampled traces."""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    service: str
    start_ns: int
    end_ns: int
    error: bool


def ms_to_ns(ms: float) -> int:
    return round(ms * NS_PER_MS)


class RequestSimulator:
    """Walks requests through a topology using one seeded random generator."""

    def __init__(
        self, topology: Topology, rng: random.Random, faults: FaultPlan | None = None
    ) -> None:
        self._topology = topology
        self._rng = rng
        self._faults = faults

    def simulate(self, start_ns: int, sampled: bool) -> list[SpanRecord]:
        """Run one request that arrives at the entry service at ``start_ns``.

        All spans are returned, because metrics are computed from every request. IDs are
        only generated when the trace is ``sampled``, i.e. when it will be written out.
        """
        spans: list[SpanRecord] = []
        trace_id = f"{self._rng.getrandbits(128):032x}" if sampled else ""
        self._visit(self._topology.entry, start_ns, trace_id, None, spans)
        return spans

    def _visit(
        self,
        name: str,
        start_ns: int,
        trace_id: str,
        parent_span_id: str | None,
        out: list[SpanRecord],
    ) -> tuple[int, bool]:
        """Simulate ``name`` handling the request. Returns ``(end_ns, failed)``."""
        service = self._topology.services[name]
        effect = self._faults.effect(name, start_ns) if self._faults else NO_EFFECT
        span_id = f"{self._rng.getrandbits(64):016x}" if trace_id else ""
        median_ms = service.base_ms * effect.latency_factor + effect.extra_ms
        own_ns = ms_to_ns(median_ms * self._rng.lognormvariate(0.0, service.jitter))
        before_calls_ns = own_ns // 2

        clock = start_ns + before_calls_ns
        error_rate = max(service.error_rate, effect.error_rate)
        failed = effect.exhausted or self._rng.random() < error_rate
        if not failed:
            clock, failed = self._call_callees(name, clock, trace_id, span_id, out)

        end_ns = clock + (own_ns - before_calls_ns)
        out.append(SpanRecord(trace_id, span_id, parent_span_id, name, start_ns, end_ns, failed))
        return end_ns, failed

    def _call_callees(
        self, caller: str, clock: int, trace_id: str, caller_span_id: str, out: list[SpanRecord]
    ) -> tuple[int, bool]:
        """Make ``caller``'s calls in order. Returns ``(clock after calls, failed)``."""
        for call in self._topology.calls_from(caller):
            if call.probability < 1.0 and self._rng.random() >= call.probability:
                continue
            callee_end, callee_failed = self._visit(
                call.callee, clock, trace_id, caller_span_id, out
            )
            timeout_ns = ms_to_ns(call.timeout_ms)
            if callee_end - clock > timeout_ns:
                return clock + timeout_ns, True  # the caller gave up waiting
            clock = callee_end
            if callee_failed:
                return clock, True  # the callee's error propagates to the caller
        return clock, False
