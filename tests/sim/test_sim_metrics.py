"""Turning spans into per-interval metrics."""

import numpy as np
import pytest

from tracehound import _format as fmt
from tracehound.sim.metrics import MetricRow, aggregate
from tracehound.sim.request import SpanRecord

S = 1_000_000_000  # one second in ns
MS = 1_000_000


def span(service: str, start_ns: int, duration_ms: float, error: bool = False) -> SpanRecord:
    return SpanRecord("", "", None, service, start_ns, start_ns + int(duration_ms * MS), error)


def values(rows: list[MetricRow], service: str, metric: str) -> dict[int, float]:
    return {r.timestamp_ms: r.value for r in rows if r.service == service and r.metric == metric}


@pytest.fixture
def rows() -> list[MetricRow]:
    # Window of 3 one-second buckets: bucket 0 has 4 spans (1 error), bucket 1 is empty,
    # bucket 2 has one span. Service "idle" receives no requests at all.
    spans = [
        span("x", 0, 10),
        span("x", 100 * MS, 20, error=True),
        span("x", 500 * MS, 30),
        span("x", 999 * MS, 40),
        span("x", 2 * S, 5),
    ]
    return aggregate(spans, ["x", "idle"], start_ns=0, end_ns=3 * S, interval_ns=S)


def test_error_rate_and_throughput(rows: list[MetricRow]) -> None:
    assert values(rows, "x", fmt.ERROR_RATE) == {0: 0.25, 2000: 0.0}
    assert values(rows, "x", fmt.THROUGHPUT) == {0: 4.0, 1000: 0.0, 2000: 1.0}


def test_latency_percentiles_match_numpy(rows: list[MetricRow]) -> None:
    expected = np.percentile([10, 20, 30, 40], [50, 95, 99])
    got = [values(rows, "x", m)[0] for m in (fmt.LATENCY_P50, fmt.LATENCY_P95, fmt.LATENCY_P99)]
    assert got == pytest.approx(expected.tolist())
    assert values(rows, "x", fmt.LATENCY_P50)[2000] == pytest.approx(5.0)


def test_empty_bucket_only_reports_zero_throughput(rows: list[MetricRow]) -> None:
    in_bucket_1 = sorted(r.metric for r in rows if r.service == "x" and r.timestamp_ms == 1000)
    assert in_bucket_1 == [fmt.THROUGHPUT]
    idle = [r for r in rows if r.service == "idle"]
    assert {r.metric for r in idle} == {fmt.THROUGHPUT} and all(r.value == 0 for r in idle)


def test_rows_are_in_file_order(rows: list[MetricRow]) -> None:
    keys = [(r.service, r.metric, r.timestamp_ms) for r in rows]
    assert keys == sorted(keys)


def test_span_starting_outside_the_window_is_a_bug() -> None:
    with pytest.raises(ValueError, match="outside the run window"):
        aggregate([span("x", 5 * S, 1)], ["x"], start_ns=0, end_ns=3 * S, interval_ns=S)


@pytest.mark.parametrize("interval_ns", [0, MS // 2, MS + 1])
def test_interval_must_be_whole_milliseconds(interval_ns: int) -> None:
    with pytest.raises(ValueError, match="milliseconds"):
        aggregate([], ["x"], start_ns=0, end_ns=S, interval_ns=interval_ns)
