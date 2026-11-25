"""A tiny, hand-written incident: every value is known, so tests can assert exact results."""

S = 1_000_000_000
START_NS = 1_767_225_600 * S
START_MS = START_NS // 1_000_000
METRICS_HEADER = "timestamp_ms,service,metric,value"

META: dict[str, object] = {
    "format_version": 1,
    "start_ns": START_NS,
    "end_ns": START_NS + 10 * S,
    "metric_interval_s": 1.0,
    "trace_sample_rate": 0.5,
    "source": "hand-written",
}
METRIC_LINES = [  # deliberately out of order: the reader sorts
    METRICS_HEADER,
    f"{START_MS + 1000},api,latency_p50_ms,13",
    f"{START_MS},db,error_rate,0.25",
    f"{START_MS},api,latency_p50_ms,12.5",
]
SPAN_RECORDS: list[dict[str, object]] = [  # also out of order
    {"trace_id": "t1", "span_id": "b", "parent_span_id": "a", "service": "db",
     "name": "SELECT", "start_ns": START_NS + 2 * S, "end_ns": START_NS + 3 * S,
     "status": "error"},
    {"trace_id": "t1", "span_id": "a", "parent_span_id": None, "service": "api",
     "name": "GET /", "start_ns": START_NS + 1 * S, "end_ns": START_NS + 4 * S,
     "status": "ok"},
]  # fmt: skip
GROUND_TRUTH: dict[str, object] = {
    "seed": 3,
    "faults": [
        {"kind": "error", "service": "db", "start_ns": START_NS + 5 * S,
         "end_ns": START_NS + 10 * S, "params": {"error_rate": 0.3}},
        {"kind": "latency", "service": "api", "start_ns": START_NS + 2 * S,
         "end_ns": START_NS + 4 * S, "params": {"added_ms": 100}},
    ],
}  # fmt: skip
