"""Aggregate spans into per-service, per-interval metrics.

Metrics are computed from *every* request, while traces are only kept for a sample. This
mirrors production, where metrics are cheap and complete but tracing is sampled.

A span is counted in the interval in which it *started*. For an interval with no requests,
latency and error rate are left out: they are undefined for zero requests and are never
invented. Throughput (0) and utilization are still written, because both are well defined.

``utilization`` = average requests in flight / capacity (Little's law: busy time divided by
interval length), plus the share of the pool held by a saturation leak at the interval start,
capped at 1.0. Like a real "pool in use / pool size" gauge, it cannot pass 100%.
"""

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import NamedTuple

import numpy as np

from tracehound import _format as fmt
from tracehound.sim.request import SpanRecord

LeakedShare = Callable[[str, int], float]  # (service, t_ns) -> share of pool held by leaks


class MetricRow(NamedTuple):
    timestamp_ms: int
    service: str
    metric: str
    value: float


def aggregate(
    spans: Iterable[SpanRecord],
    capacities: Mapping[str, float],
    start_ns: int,
    end_ns: int,
    interval_ns: int,
    leaked_share: LeakedShare | None = None,
) -> list[MetricRow]:
    """Rows for every service in ``capacities``, sorted (service, metric, timestamp)."""
    if interval_ns <= 0 or interval_ns % fmt.NS_PER_MS:
        raise ValueError("interval must be a positive whole number of milliseconds")
    n_buckets = math.ceil((end_ns - start_ns) / interval_ns)
    bucket_starts = [start_ns + b * interval_ns for b in range(n_buckets)]
    by_service: dict[str, list[SpanRecord]] = {name: [] for name in capacities}
    for span in spans:
        by_service[span.service].append(span)

    rows: list[MetricRow] = []
    for name in sorted(by_service):
        leaked = [leaked_share(name, t) if leaked_share else 0.0 for t in bucket_starts]
        rows.extend(
            _service_rows(
                name, by_service[name], bucket_starts, interval_ns, capacities[name], leaked
            )
        )
    return rows


def _service_rows(
    service: str,
    spans: Sequence[SpanRecord],
    bucket_starts: Sequence[int],
    interval_ns: int,
    capacity: float,
    leaked: Sequence[float],
) -> list[MetricRow]:
    n, n_buckets = len(spans), len(bucket_starts)
    starts = np.fromiter((s.start_ns for s in spans), dtype=np.int64, count=n)
    durations_ms = np.fromiter(
        ((s.end_ns - s.start_ns) / fmt.NS_PER_MS for s in spans), dtype=np.float64, count=n
    )
    errors = np.fromiter((s.error for s in spans), dtype=np.float64, count=n)
    buckets = (starts - bucket_starts[0]) // interval_ns
    if n and (buckets.min() < 0 or buckets.max() >= n_buckets):
        raise ValueError(f"{service}: span starts outside the run window")

    counts = np.bincount(buckets, minlength=n_buckets)
    error_counts = np.bincount(buckets, weights=errors, minlength=n_buckets)
    busy_ms = np.bincount(buckets, weights=durations_ms, minlength=n_buckets)
    order = np.argsort(buckets, kind="stable")
    sorted_durations = durations_ms[order]
    bounds = np.searchsorted(buckets[order], np.arange(n_buckets + 1))

    active = [b for b in range(n_buckets) if counts[b]]
    latency: dict[str, list[float]] = {
        fmt.LATENCY_P50: [],
        fmt.LATENCY_P95: [],
        fmt.LATENCY_P99: [],
    }
    for b in active:
        values = np.percentile(sorted_durations[bounds[b] : bounds[b + 1]], [50, 95, 99])
        for metric, value in zip(latency, values, strict=True):
            latency[metric].append(float(value))

    ts = [t // fmt.NS_PER_MS for t in bucket_starts]
    interval_ms = interval_ns / fmt.NS_PER_MS
    rows = [MetricRow(ts[b], service, fmt.ERROR_RATE, error_counts[b] / counts[b]) for b in active]
    for metric, series in latency.items():
        rows.extend(
            MetricRow(ts[b], service, metric, v) for b, v in zip(active, series, strict=True)
        )
    rows.extend(
        MetricRow(ts[b], service, fmt.THROUGHPUT, counts[b] * 1000 / interval_ms)
        for b in range(n_buckets)
    )
    in_use = np.minimum(1.0, busy_ms / interval_ms / capacity + np.asarray(leaked))
    rows.extend(MetricRow(ts[b], service, fmt.UTILIZATION, in_use[b]) for b in range(n_buckets))
    return [r._replace(value=float(r.value)) for r in rows]
