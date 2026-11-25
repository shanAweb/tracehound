"""Loading a valid folder: exact values, sorting, optional files and read-only data."""

from pathlib import Path

import numpy as np
import pytest

import tracehound
from tests.ingest.conftest import MakeIncident
from tests.ingest.sample import META, METRICS_HEADER, START_MS, START_NS, S
from tracehound.ingest import ROOT, Incident, PlantedFault, load


@pytest.fixture
def incident(make_incident: MakeIncident) -> Incident:
    return load(make_incident())


def test_meta_is_read(incident: Incident) -> None:
    m = incident.meta
    assert (m.format_version, m.start_ns, m.end_ns) == (1, START_NS, START_NS + 10 * S)
    assert (m.metric_interval_s, m.trace_sample_rate, m.source) == (1.0, 0.5, "hand-written")
    assert m.duration_s == 10.0


def test_optional_meta_fields_default_to_none(make_incident: MakeIncident) -> None:
    meta = {k: v for k, v in META.items() if k not in ("trace_sample_rate", "source")}
    m = load(make_incident(meta=meta)).meta
    assert (m.trace_sample_rate, m.source) == (None, None)


def test_metrics_are_grouped_into_sorted_series(incident: Incident) -> None:
    assert list(incident.metrics) == [("api", "latency_p50_ms"), ("db", "error_rate")]
    api = incident.metrics["api", "latency_p50_ms"]
    assert api.timestamps_ms.tolist() == [START_MS, START_MS + 1000]
    assert api.values.tolist() == [12.5, 13.0]
    assert incident.metrics.services == ("api", "db")
    assert list(incident.metrics.of_service("db")) == ["error_rate"]


def test_spans_are_columns_sorted_by_start(incident: Incident) -> None:
    spans = incident.spans
    assert len(spans) == 2
    assert spans.span_id.tolist() == ["a", "b"]
    assert spans.parent_span_id.tolist() == [ROOT, "a"]
    assert spans.service.tolist() == ["api", "db"]
    assert spans.name.tolist() == ["GET /", "SELECT"]
    assert spans.duration_ns.tolist() == [3 * S, 1 * S]
    assert spans.error.tolist() == [False, True]
    assert spans.of_service("db").span_id.tolist() == ["b"]


def test_ground_truth_is_sorted_by_onset(incident: Incident) -> None:
    truth = incident.ground_truth
    assert truth is not None and truth.seed == 3
    assert truth.faults[0] == PlantedFault(
        "latency", "api", START_NS + 2 * S, START_NS + 4 * S, {"added_ms": 100.0}
    )
    assert [f.service for f in truth.faults] == ["api", "db"]
    assert truth.services == ("api", "db")


def test_ground_truth_is_optional(make_incident: MakeIncident) -> None:
    assert load(make_incident(ground_truth=None)).ground_truth is None


def test_services_is_the_union_of_metrics_and_traces(make_incident: MakeIncident) -> None:
    lines = [METRICS_HEADER, f"{START_MS},cache,throughput_rps,9"]
    assert load(make_incident(metrics=lines)).services == ("api", "cache", "db")


def test_parent_span_id_missing_or_empty_means_root(make_incident: MakeIncident) -> None:
    lines = [
        '{"trace_id": "t", "span_id": "x", "service": "api", "name": "n", '
        f'"start_ns": {START_NS}, "end_ns": {START_NS}, "status": "ok"}}',
        '{"trace_id": "t2", "span_id": "y", "parent_span_id": "", "service": "api", '
        f'"name": "n", "start_ns": {START_NS}, "end_ns": {START_NS}, "status": "ok", '
        '"attributes": {"http.method": "GET"}}',  # unknown fields are ignored
    ]
    assert load(make_incident(traces=lines)).spans.parent_span_id.tolist() == [ROOT, ROOT]


def test_empty_metrics_and_traces_are_valid(make_incident: MakeIncident) -> None:
    incident = load(make_incident(metrics=[METRICS_HEADER], traces=[]))
    assert (len(incident.metrics), len(incident.spans), incident.services) == (0, 0, ())


def test_line_order_does_not_matter(make_incident: MakeIncident) -> None:
    folder = make_incident()
    before = load(folder)
    _reverse_lines(folder / "metrics.csv", keep_header=True)
    _reverse_lines(folder / "traces.jsonl", keep_header=False)
    after = load(folder)
    assert after.spans.span_id.tolist() == before.spans.span_id.tolist()
    assert list(after.metrics) == list(before.metrics)
    for key, series in before.metrics.items():
        assert np.array_equal(after.metrics[key].timestamps_ms, series.timestamps_ms)
        assert np.array_equal(after.metrics[key].values, series.values)


def _reverse_lines(path: Path, keep_header: bool) -> None:
    lines = path.read_text().splitlines(keepends=True)
    head, body = (lines[:1], lines[1:]) if keep_header else ([], lines)
    path.write_text("".join(head + body[::-1]))


def test_arrays_are_read_only(incident: Incident) -> None:
    with pytest.raises(ValueError, match="read-only"):
        incident.spans.start_ns[0] = 0
    with pytest.raises(ValueError, match="read-only"):
        incident.metrics["api", "latency_p50_ms"].values[0] = 0.0


def test_repr_is_a_short_summary(incident: Incident) -> None:
    text = repr(incident)
    assert "services=2" in text and "spans=2" in text and "planted_faults=2" in text
    assert repr(incident.spans) == "Spans(n=2, services=2)"


def test_load_is_exposed_at_the_top_level() -> None:
    assert tracehound.load is load
