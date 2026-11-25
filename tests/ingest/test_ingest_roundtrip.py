"""Simulator -> disk -> ``load``: what is read back is exactly what was simulated."""

from pathlib import Path

import numpy as np
import pytest

from tracehound import _format as fmt
from tracehound.ingest import ROOT, Incident, load
from tracehound.sim import Fault, SimRun, System


@pytest.fixture(scope="module")
def run() -> SimRun:
    fault = Fault("latency", "payments-db", at="10s", duration="15s", strength=300)
    return System.example("shop").run(duration="40s", rps=30, seed=11, faults=[fault])


@pytest.fixture(scope="module")
def incident(run: SimRun, tmp_path_factory: pytest.TempPathFactory) -> Incident:
    return load(run.save(tmp_path_factory.mktemp("roundtrip")))


def test_meta_round_trips(run: SimRun, incident: Incident) -> None:
    m = incident.meta
    read_back = {
        "format_version": m.format_version,
        "start_ns": m.start_ns,
        "end_ns": m.end_ns,
        "metric_interval_s": m.metric_interval_s,
        "trace_sample_rate": m.trace_sample_rate,
        "source": m.source,
    }
    assert read_back == run.meta


def test_every_metric_value_round_trips_at_4_decimals(run: SimRun, incident: Incident) -> None:
    expected: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for row in run.metric_rows:
        value = float(fmt.format_value(row.value))
        expected.setdefault((row.service, row.metric), []).append((row.timestamp_ms, value))
    assert list(incident.metrics) == sorted(expected)
    for key, samples in expected.items():
        series = incident.metrics[key]
        assert series.timestamps_ms.tolist() == [t for t, _ in sorted(samples)]
        assert series.values.tolist() == [v for _, v in sorted(samples)]


def test_every_span_round_trips(run: SimRun, incident: Incident) -> None:
    spans = incident.spans
    assert len(spans) == len(run.spans) > 0
    assert spans.trace_id.tolist() == [s.trace_id for s in run.spans]
    assert spans.span_id.tolist() == [s.span_id for s in run.spans]
    assert spans.parent_span_id.tolist() == [s.parent_span_id or ROOT for s in run.spans]
    assert spans.service.tolist() == [s.service for s in run.spans]
    assert spans.start_ns.tolist() == [s.start_ns for s in run.spans]
    assert spans.end_ns.tolist() == [s.end_ns for s in run.spans]
    assert spans.error.tolist() == [s.error for s in run.spans]
    operations = {name: s.operation for name, s in run.topology.services.items()}
    assert spans.name.tolist() == [operations[s.service] for s in run.spans]


def test_ground_truth_round_trips(run: SimRun, incident: Incident) -> None:
    truth = incident.ground_truth
    assert truth is not None
    assert truth.seed == run.ground_truth["seed"]
    faults = run.ground_truth["faults"]
    assert isinstance(faults, list) and len(truth.faults) == len(faults) == 1
    planted, recorded = truth.faults[0], faults[0]
    assert isinstance(recorded, dict)
    assert planted.kind == recorded["kind"] and planted.service == recorded["service"]
    assert (planted.start_ns, planted.end_ns) == (recorded["start_ns"], recorded["end_ns"])
    assert planted.params == recorded["params"] == {"added_ms": 300.0}


def test_services_match_the_topology(run: SimRun, incident: Incident) -> None:
    assert incident.services == run.topology.service_names


def test_planted_latency_is_visible_in_the_loaded_spans(incident: Incident) -> None:
    db = incident.spans.of_service("payments-db")
    truth = incident.ground_truth
    assert truth is not None
    fault = truth.faults[0]
    during = (db.start_ns >= fault.start_ns) & (db.start_ns < fault.end_ns)
    median_ms = {
        "before/after": float(np.median(db.duration_ns[~during])) / fmt.NS_PER_MS,
        "during": float(np.median(db.duration_ns[during])) / fmt.NS_PER_MS,
    }
    assert 30 < median_ms["before/after"] < 50  # payments-db's base is 40 ms
    assert 310 < median_ms["during"] < 370  # 40 + 300 ms


def test_loading_twice_gives_identical_data(incident: Incident) -> None:
    assert incident.path is not None
    again = load(Path(incident.path))
    assert again.spans.span_id.tolist() == incident.spans.span_id.tolist()
    for key, series in incident.metrics.items():
        assert np.array_equal(again.metrics[key].values, series.values)
