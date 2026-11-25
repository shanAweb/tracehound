"""Invalid input: every problem fails loudly, naming the file, the line and the reason."""

import json
import re
from pathlib import Path

import pytest

from tests.ingest.conftest import MakeIncident
from tests.ingest.sample import (
    GROUND_TRUTH,
    META,
    METRICS_HEADER,
    SPAN_RECORDS,
    START_MS,
    START_NS,
    S,
)
from tracehound.ingest import IncidentFormatError, load


def fails(folder: Path, file_and_line: str, reason: str) -> None:
    """Loading ``folder`` raises an error whose message is ``<path>:<line>: ...reason...``."""
    with pytest.raises(IncidentFormatError) as info:
        load(folder)
    message = str(info.value)
    assert message.startswith(f"{folder / file_and_line}: "), message
    assert re.search(reason, message), message


def meta_with(**changes: object) -> dict[str, object]:
    return {k: v for k, v in {**META, **changes}.items() if v is not ...}


def span_line(**changes: object) -> str:
    return json.dumps({k: v for k, v in {**SPAN_RECORDS[1], **changes}.items() if v is not ...})


def test_missing_folder_and_missing_file(make_incident: MakeIncident, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="incident folder not found"):
        load(tmp_path / "nope")
    folder = make_incident()
    (folder / "traces.jsonl").unlink()
    fails(folder, "traces.jsonl", "required file is missing")


@pytest.mark.parametrize(
    ("meta", "where", "reason"),
    [
        ("{oops", "meta.json:1", "invalid JSON"),
        ("[1, 2]", "meta.json", "expected a JSON object"),
        ('{"start_ns": NaN}', "meta.json", "NaN is not allowed"),
        (meta_with(start_ns=...), "meta.json", "missing required field 'start_ns'"),
        (meta_with(start_ns="12"), "meta.json", "start_ns must be an integer, got '12'"),
        (meta_with(start_ns=True), "meta.json", "start_ns must be an integer, got True"),
        (meta_with(end_ns=START_NS), "meta.json", "end_ns .* must be after start_ns"),
        (meta_with(format_version=2), "meta.json", r"format_version 2 .*upgrade tracehound"),
        (meta_with(metric_interval_s=0), "meta.json", "metric_interval_s must be > 0"),
        (meta_with(trace_sample_rate=1.5), "meta.json", r"trace_sample_rate must be in \(0, 1\]"),
        (meta_with(source=""), "meta.json", "source must be a non-empty string"),
    ],
)
def test_bad_meta(
    make_incident: MakeIncident, meta: dict[str, object] | str, where: str, reason: str
) -> None:
    fails(make_incident(meta=meta), where, reason)


@pytest.mark.parametrize(
    ("lines", "where", "reason"),
    [
        ([], "metrics.csv:1", "the file is empty"),
        (["time,service,metric,value"], "metrics.csv:1", "header must be"),
        ([METRICS_HEADER, f"{START_MS},api,p50"], "metrics.csv:2", "expected 4 fields, got 3"),
        ([METRICS_HEADER, "1e12,api,p50,1"], "metrics.csv:2", "timestamp_ms must be an integer"),
        ([METRICS_HEADER, f"{START_MS},api,p50,fast"], "metrics.csv:2", "must be a number"),
        ([METRICS_HEADER, f"{START_MS},api,p50,nan"], "metrics.csv:2", "must be finite"),
        ([METRICS_HEADER, f"{START_MS},,p50,1"], "metrics.csv:2", "service must not be empty"),
        ([METRICS_HEADER, f"{START_MS - 1},api,p50,1"], "metrics.csv:2", "outside the record"),
        ([METRICS_HEADER, f"{START_MS + 10_000},api,p50,1"], "metrics.csv:2", "outside the"),
        (
            [METRICS_HEADER, f"{START_MS},api,p50,1", "", f"{START_MS},api,p50,2"],
            "metrics.csv:4",
            r"duplicate sample for api p50 \(first on line 2\)",
        ),
    ],
)
def test_bad_metrics(
    make_incident: MakeIncident, lines: list[str], where: str, reason: str
) -> None:
    fails(make_incident(metrics=lines), where, reason)


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ('{"trace_id": ', "invalid JSON"),
        ("[1, 2]", "expected a JSON object, got \\[1, 2\\]"),
        (span_line(trace_id=...), "missing required field 'trace_id'"),
        (span_line(span_id=""), "span_id must be a non-empty string"),
        (span_line(parent_span_id=7), "parent_span_id must be a non-empty string"),
        (span_line(start_ns=1.5e18), "start_ns must be an integer"),
        (span_line(end_ns=2**63), "end_ns does not fit in a 64-bit integer"),
        (span_line(end_ns=START_NS), r"end_ns \(.*\) is before start_ns"),
        (span_line(start_ns=START_NS + 10 * S), "start_ns .* outside the recording window"),
        (span_line(status="OK"), "status must be 'ok' or 'error', got 'OK'"),
        (span_line(span_id="b", trace_id="t1"), r"duplicate span_id 'b' .*first on line 1"),
    ],
)
def test_bad_span_is_reported_on_its_line(
    make_incident: MakeIncident, line: str, reason: str
) -> None:
    lines = [json.dumps(SPAN_RECORDS[0]), "", line]  # blank lines count but are skipped
    fails(make_incident(traces=lines), "traces.jsonl:3", reason)


def fault_with(**changes: object) -> dict[str, object]:
    faults = GROUND_TRUTH["faults"]
    assert isinstance(faults, list)
    fault = {k: v for k, v in {**faults[0], **changes}.items() if v is not ...}
    return {"seed": 1, "faults": [fault]}


@pytest.mark.parametrize(
    ("truth", "reason"),
    [
        ({"seed": 1}, "missing required field 'faults'"),
        ({"seed": "x", "faults": []}, "seed must be an integer"),
        ({"faults": {}}, "faults must be a list"),
        ({"faults": [3]}, r"faults\[0\] must be a JSON object"),
        (fault_with(service=...), r"faults\[0\]: missing required field 'service'"),
        (fault_with(end_ns=START_NS), r"faults\[0\]: end_ns .* must be after start_ns"),
        (fault_with(params=[]), r"faults\[0\]: params must be a JSON object"),
        (fault_with(params={"added_ms": "x"}), r"faults\[0\]: params.added_ms must be a number"),
    ],
)
def test_bad_ground_truth(
    make_incident: MakeIncident, truth: dict[str, object], reason: str
) -> None:
    fails(make_incident(ground_truth=truth), "ground_truth.json", reason)


def test_invalid_utf8_is_reported(make_incident: MakeIncident) -> None:
    folder = make_incident()
    (folder / "metrics.csv").write_bytes(METRICS_HEADER.encode() + b"\n\xff\xfe,api,p50,1\n")
    fails(folder, "metrics.csv", "not valid UTF-8")


def test_error_carries_its_parts(make_incident: MakeIncident) -> None:
    folder = make_incident(metrics=[METRICS_HEADER, f"{START_MS},api,p50,x"])
    with pytest.raises(IncidentFormatError) as info:
        load(folder)
    error = info.value
    assert (error.path, error.line) == (folder / "metrics.csv", 2)
    assert error.problem == "value must be a number, got 'x'"
    assert isinstance(error, ValueError)
    assert error.__context__ is None  # no unrelated exception chained in the traceback
    assert type(error).__module__ == "tracehound"  # tracebacks show the public name


def test_non_finite_json_error_is_not_chained(make_incident: MakeIncident) -> None:
    with pytest.raises(IncidentFormatError) as info:
        load(make_incident(meta='{"start_ns": Infinity}'))
    assert info.value.__cause__ is None and info.value.__suppress_context__
