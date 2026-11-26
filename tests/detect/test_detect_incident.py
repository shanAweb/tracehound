"""``detect`` on simulated incidents, read back from disk exactly as a user would."""

from pathlib import Path

import pytest

from tracehound import load
from tracehound.detect import DetectConfig, Detection, detect
from tracehound.ingest import Incident
from tracehound.sim import Fault, System

S = 1_000_000_000
FAULT_AT_S = 100.3  # not on a metric-interval boundary


def incident(
    folder: Path, *faults: Fault, interval_s: float = 1.0, duration: str = "4m"
) -> Incident:
    run = System.example("shop").run(
        duration=duration, rps=50, seed=21, faults=list(faults), metric_interval_s=interval_s
    )
    return load(run.save(folder))


@pytest.fixture(scope="module")
def latency(tmp_path_factory: pytest.TempPathFactory) -> Detection:
    fault = Fault("latency", "payments-db", at=FAULT_AT_S)
    return detect(incident(tmp_path_factory.mktemp("latency"), fault))


@pytest.fixture(scope="module")
def healthy(tmp_path_factory: pytest.TempPathFactory) -> Incident:
    return incident(tmp_path_factory.mktemp("healthy"))


def test_a_healthy_run_has_no_anomalies(healthy: Incident) -> None:
    detection = detect(healthy)
    assert detection.anomalies == ()
    assert detection.signals_checked == 48 and detection.skipped == ()


def test_the_cause_and_its_victims_are_flagged_but_not_bystanders(latency: Detection) -> None:
    assert latency.services == ("cart", "checkout", "frontend", "payments", "payments-db")


def test_the_cause_shows_the_largest_latency_shift(latency: Detection) -> None:
    p50 = {a.service: a.shift for a in latency.anomalies if a.signal == "latency_p50_ms"}
    assert max(p50, key=p50.__getitem__) == "payments-db"


def test_onset_is_the_metric_interval_containing_the_fault(latency: Detection) -> None:
    (cause,) = [a for a in latency.of_service("payments-db") if a.signal == "latency_p50_ms"]
    start_ns = 1_767_225_600 * S
    assert cause.onset_ns - start_ns == 100 * S  # the fault began at +100.3 s
    assert cause.resolution_ns == S
    assert cause.baseline == pytest.approx(40, abs=2) and cause.observed > 850


def test_anomalies_are_sorted_by_onset(latency: Detection) -> None:
    keys = [(a.onset_ns, a.service, a.signal, a.direction) for a in latency.anomalies]
    assert keys == sorted(keys)


def test_an_error_fault_raises_error_rate_at_the_cause(tmp_path: Path) -> None:
    detection = detect(incident(tmp_path, Fault("error", "catalog-db", at=FAULT_AT_S)))
    (errors,) = [a for a in detection.of_service("catalog-db") if a.signal == "error_rate"]
    assert errors.observed == pytest.approx(0.3, abs=0.05)
    # frontend calls auth before catalog, so catalog's errors cannot touch auth. (The checkout
    # subtree is not safe to assert on: frontend now fails before calling it about 30% of
    # the time, and that real drop in traffic is detected in some seeds and not others.)
    assert "auth" not in detection.services


def test_coarse_metrics_give_coarse_onsets(tmp_path: Path) -> None:
    # 15 s metrics need a longer recording: 10 min gives 40 points, 13 of them baseline.
    fault = Fault("latency", "auth", at=250.3)
    detection = detect(incident(tmp_path, fault, interval_s=15, duration="10m"))
    (cause,) = [a for a in detection.of_service("auth") if a.signal == "latency_p50_ms"]
    assert cause.resolution_ns == 15 * S
    assert cause.onset_ns - 1_767_225_600 * S == 240 * S  # the 15 s interval holding +250.3 s


def test_a_short_baseline_is_reported_as_skipped(healthy: Incident) -> None:
    detection = detect(healthy, DetectConfig(min_baseline_points=200))
    assert detection.signals_checked == 0 and len(detection.skipped) == 48
