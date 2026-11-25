"""``System``: drive synthetic traffic through a topology and record its telemetry."""

import random
from dataclasses import dataclass
from pathlib import Path

from tracehound import _format as fmt
from tracehound.sim.examples import example
from tracehound.sim.metrics import MetricRow, aggregate
from tracehound.sim.request import RequestSimulator, SpanRecord
from tracehound.sim.topology import Topology
from tracehound.sim.units import parse_duration, seconds_to_ns
from tracehound.sim.writer import JsonValue, write_incident

# 2026-01-01T00:00:00Z: a fixed default start, so the same seed gives the same timestamps.
DEFAULT_START_NS = 1_767_225_600 * fmt.NS_PER_S


@dataclass(frozen=True)
class SimRun:
    """The recorded telemetry of one simulated run, ready to save as an incident folder."""

    topology: Topology
    meta: dict[str, JsonValue]
    metric_rows: tuple[MetricRow, ...]
    spans: tuple[SpanRecord, ...]  # sampled traces only, sorted by (start_ns, span_id)
    ground_truth: dict[str, JsonValue]
    n_requests: int

    def save(self, folder: str | Path) -> Path:
        """Write meta.json, metrics.csv, traces.jsonl and ground_truth.json into ``folder``."""
        span_names = {name: s.operation for name, s in self.topology.services.items()}
        return write_incident(
            folder, self.meta, self.metric_rows, self.spans, span_names, self.ground_truth
        )


class System:
    """A simulated microservice system. Same arguments and seed -> identical output."""

    def __init__(self, topology: Topology) -> None:
        self.topology = topology

    @classmethod
    def example(cls, name: str) -> "System":
        """A ready-made system, e.g. ``System.example("shop")``."""
        return cls(example(name))

    def run(
        self,
        duration: str | float = "10m",
        rps: float = 50.0,
        seed: int = 0,
        *,
        trace_sample_rate: float = 0.1,
        metric_interval_s: float = 1.0,
        start_ns: int = DEFAULT_START_NS,
    ) -> SimRun:
        """Send Poisson-distributed traffic at ``rps`` for ``duration`` and record it.

        Metrics come from every request. Traces are kept for ``trace_sample_rate`` of them.
        Only spans starting inside ``[start_ns, end_ns)`` are recorded.
        """
        if not rps > 0:
            raise ValueError("rps must be > 0")
        if not 0.0 < trace_sample_rate <= 1.0:
            raise ValueError("trace_sample_rate must be in (0, 1]")
        interval_ns = seconds_to_ns(parse_duration(metric_interval_s))
        end_ns = start_ns + seconds_to_ns(parse_duration(duration))

        rng = random.Random(seed)
        simulator = RequestSimulator(self.topology, rng)
        all_spans: list[SpanRecord] = []
        sampled_spans: list[SpanRecord] = []
        n_requests = 0
        offset_s = rng.expovariate(rps)
        while (arrival_ns := start_ns + seconds_to_ns(offset_s)) < end_ns:
            sampled = rng.random() < trace_sample_rate
            spans = simulator.simulate(arrival_ns, sampled)
            all_spans.extend(spans)
            if sampled:
                sampled_spans.extend(spans)
            n_requests += 1
            offset_s += rng.expovariate(rps)

        # The recording window is [start_ns, end_ns), like an export cut at end time: callee
        # spans of requests arriving in the last milliseconds may start after it, and are
        # not recorded.
        all_spans = [s for s in all_spans if s.start_ns < end_ns]
        sampled_spans = [s for s in sampled_spans if s.start_ns < end_ns]
        rows = aggregate(all_spans, self.topology.service_names, start_ns, end_ns, interval_ns)
        meta: dict[str, JsonValue] = {
            "format_version": fmt.FORMAT_VERSION,
            "start_ns": start_ns,
            "end_ns": end_ns,
            "metric_interval_s": interval_ns / fmt.NS_PER_S,
            "trace_sample_rate": trace_sample_rate,
            "source": "tracehound.sim",
        }
        ground_truth: dict[str, JsonValue] = {"seed": seed, "faults": []}
        sampled_spans.sort(key=lambda s: (s.start_ns, s.span_id))
        return SimRun(
            self.topology, meta, tuple(rows), tuple(sampled_spans), ground_truth, n_requests
        )
