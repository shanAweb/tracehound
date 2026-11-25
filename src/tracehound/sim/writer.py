"""Write telemetry to disk in the incident folder format (see README).

Every byte is deterministic: rows and spans are sorted, numbers are rounded the same way
every time, JSON keys are ordered, and line endings are always ``\\n`` on every OS.
"""

import csv
import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from tracehound import _format as fmt
from tracehound.sim.metrics import MetricRow
from tracehound.sim.request import SpanRecord

JsonValue = int | float | str | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


def write_incident(
    folder: str | Path,
    meta: Mapping[str, JsonValue],
    metric_rows: Iterable[MetricRow],
    spans: Iterable[SpanRecord],
    span_names: Mapping[str, str],
    ground_truth: Mapping[str, JsonValue],
) -> Path:
    """Write the four incident files into ``folder`` (created if needed) and return its path."""
    path = Path(folder)
    path.mkdir(parents=True, exist_ok=True)
    _write_json(path / fmt.META_FILE, meta)
    _write_metrics(path / fmt.METRICS_FILE, metric_rows)
    _write_traces(path / fmt.TRACES_FILE, spans, span_names)
    _write_json(path / fmt.GROUND_TRUTH_FILE, ground_truth)
    return path


def _write_json(path: Path, data: Mapping[str, JsonValue]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _write_metrics(path: Path, rows: Iterable[MetricRow]) -> None:
    ordered = sorted(rows, key=lambda r: (r.service, r.metric, r.timestamp_ms))
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(fmt.METRICS_HEADER)
        for row in ordered:
            writer.writerow(
                [row.timestamp_ms, row.service, row.metric, fmt.format_value(row.value)]
            )


def _write_traces(path: Path, spans: Iterable[SpanRecord], span_names: Mapping[str, str]) -> None:
    ordered = sorted(spans, key=lambda s: (s.start_ns, s.span_id))
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for span in ordered:
            if not span.span_id:
                raise ValueError("cannot write a span from an unsampled trace (it has no IDs)")
            record = dict(
                zip(
                    fmt.TRACE_FIELDS,
                    (
                        span.trace_id,
                        span.span_id,
                        span.parent_span_id,
                        span.service,
                        span_names[span.service],
                        span.start_ns,
                        span.end_ns,
                        fmt.STATUS_ERROR if span.error else fmt.STATUS_OK,
                    ),
                    strict=True,
                )
            )
            f.write(json.dumps(record) + "\n")
