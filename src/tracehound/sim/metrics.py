"""Aggregate spans into per-service, per-interval metrics.

Metrics are computed from *every* request, while traces are only kept for a sample. This
mirrors production, where metrics are cheap and complete but tracing is sampled.

A span is counted in the interval in which it *started*. For an interval with no requests
only ``throughput_rps = 0`` is written: a latency or error rate of nothing is undefined,
so it is left out rather than invented.
"""

import math
from collections.abc import Iterable, Sequence
from typing import NamedTuple

import numpy as np

from tracehound import _format as fmt
from tracehound.sim.request import SpanRecord


class MetricRow(NamedTuple):
    timestamp_ms: int
    service: str
    metric: str
    value: float


def aggregate(
    spans: Iterable[SpanRecord],
    services: Sequence[str],
    start_ns: int,
    end_ns: int,
    interval_ns: int,
) -> list[MetricRow]:
    """Return rows sorted by (service, metric, timestamp), the order metrics.csv requires."""
    if interval_ns <= 0 or interval_ns % fmt.NS_PER_MS:
        raise ValueError("interval must be a positive whole number of milliseconds")
    n_buckets = math.ceil((end_ns - start_ns) / interval_ns)
    by_service: dict[str, list[SpanRecord]] = {name: [] for name in services}
    for span in spans:
        by_service[span.service].append(span)

    rows: list[MetricRow] = []
    for name in sorted(by_service):
        rows.extend(_service_rows(name, by_service[name], start_ns, n_buckets, interval_ns))
    return rows


def _service_rows(
    service: str,
    spans: Sequence[SpanRecord],
    start_ns: int,
    n_buckets: int,
    interval_ns: int,
) -> list[MetricRow]:
    n = len(spans)
    starts = np.fromiter((s.start_ns for s in spans), dtype=np.int64, count=n)
    durations_ms = np.fromiter(
        ((s.end_ns - s.start_ns) / fmt.NS_PER_MS for s in spans), dtype=np.float64, count=n
    )
    errors = np.fromiter((s.error for s in spans), dtype=np.float64, count=n)
    buckets = (starts - start_ns) // interval_ns
    if n and (buckets.min() < 0 or buckets.max() >= n_buckets):
        raise ValueError(f"{service}: span starts outside the run window")

    counts = np.bincount(buckets, minlength=n_buckets)
    error_counts = np.bincount(buckets, weights=errors, minlength=n_buckets)
    order = np.argsort(buckets, kind="stable")
    sorted_durations = durations_ms[order]
    bounds = np.searchsorted(buckets[order], np.arange(n_buckets + 1))

    timestamps = [(start_ns + b * interval_ns) // fmt.NS_PER_MS for b in range(n_buckets)]
    percentiles: dict[str, list[float]] = {
        fmt.LATENCY_P50: [],
        fmt.LATENCY_P95: [],
        fmt.LATENCY_P99: [],
    }
    for b in range(n_buckets):
        if counts[b]:
            p50, p95, p99 = np.percentile(sorted_durations[bounds[b] : bounds[b + 1]], [50, 95, 99])
            for key, value in zip(percentiles, (p50, p95, p99), strict=True):
                percentiles[key].append(float(value))

    interval_s = interval_ns / fmt.NS_PER_S
    active = [b for b in range(n_buckets) if counts[b]]
    rows = [
        MetricRow(timestamps[b], service, fmt.ERROR_RATE, float(error_counts[b] / counts[b]))
        for b in active
    ]
    for metric, values in percentiles.items():
        rows.extend(
            MetricRow(timestamps[b], service, metric, v)
            for b, v in zip(active, values, strict=True)
        )
    rows.extend(
        MetricRow(timestamps[b], service, fmt.THROUGHPUT, float(counts[b] / interval_s))
        for b in range(n_buckets)
    )
    return rows
