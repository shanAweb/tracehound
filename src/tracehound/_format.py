"""Constants for the incident folder format, shared by every writer and reader.

The format itself is specified in README.md ("Input format: the incident folder").
Keeping names here means the simulator (writer) and ingest (reader) cannot drift apart.
"""

from typing import Final

JsonValue = int | float | str | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

FORMAT_VERSION: Final = 1

META_FILE: Final = "meta.json"
METRICS_FILE: Final = "metrics.csv"
TRACES_FILE: Final = "traces.jsonl"
GROUND_TRUTH_FILE: Final = "ground_truth.json"

METRICS_HEADER: Final = ("timestamp_ms", "service", "metric", "value")
TRACE_FIELDS: Final = (
    "trace_id",
    "span_id",
    "parent_span_id",
    "service",
    "name",
    "start_ns",
    "end_ns",
    "status",
)

# Standard metric names (alphabetical: this is also their row order in metrics.csv).
ERROR_RATE: Final = "error_rate"
LATENCY_P50: Final = "latency_p50_ms"
LATENCY_P95: Final = "latency_p95_ms"
LATENCY_P99: Final = "latency_p99_ms"
THROUGHPUT: Final = "throughput_rps"
UTILIZATION: Final = "utilization"

STATUS_OK: Final = "ok"
STATUS_ERROR: Final = "error"

NS_PER_MS: Final = 1_000_000
NS_PER_S: Final = 1_000_000_000


def format_value(value: float, decimals: int = 4) -> str:
    """Render a number deterministically: fixed rounding, no trailing zeros, no "-0".

    >>> format_value(41.20004), format_value(3.0), format_value(-0.00001)
    ('41.2', '3', '0')
    """
    if decimals < 1:
        raise ValueError("decimals must be >= 1")
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text
