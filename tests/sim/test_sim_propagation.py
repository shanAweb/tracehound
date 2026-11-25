"""How planted faults spread through the shop system: the spec's incident stories, measured.

Each test runs 2 minutes at 50 rps with a fixed seed. Expected values are worked out from the
topology by hand. For example, for an error fault of 0.3 in payments-db, checkout fails when
either its cart call or its payments call fails: 1 - 0.7 * 0.7 = 0.51.
"""

import json
from pathlib import Path
from statistics import mean

import pytest

from tracehound import _format as fmt
from tracehound.sim import Fault, SimRun, System

BEFORE, AFTER = (5, 55), (65, 115)  # seconds; skips the transition around a +60 s onset
SERVICES = ["frontend", "auth", "catalog", "catalog-db", "checkout", "cart", "payments"]


def simulate(*faults: Fault) -> SimRun:
    return System.example("shop").run(duration="2m", rps=50, seed=3, faults=faults)


def avg(run: SimRun, service: str, metric: str, window: tuple[int, int]) -> float:
    """Mean of the per-interval values of ``metric`` whose interval starts inside ``window``."""
    t0 = run.meta["start_ns"]
    assert isinstance(t0, int)
    lo, hi = (t0 // fmt.NS_PER_MS + s * 1000 for s in window)
    values = [
        r.value
        for r in run.metric_rows
        if r.service == service and r.metric == metric and lo <= r.timestamp_ms < hi
    ]
    return mean(values) if values else float("nan")


@pytest.fixture(scope="module")
def healthy() -> SimRun:
    return simulate()


@pytest.fixture(scope="module")
def slow_db() -> SimRun:
    return simulate(Fault("latency", "payments-db", at="+60s"))  # +850 ms


def test_latency_fault_reproduces_the_spec_story(slow_db: SimRun) -> None:
    # payments-db slows to ~890 ms > cart's 500 ms timeout: cart and checkout fail, and
    # frontend fails for the ~30% of requests that check out.
    assert avg(slow_db, "payments-db", fmt.LATENCY_P50, AFTER) == pytest.approx(890, rel=0.05)
    assert avg(slow_db, "cart", fmt.ERROR_RATE, AFTER) > 0.95
    assert avg(slow_db, "checkout", fmt.ERROR_RATE, AFTER) > 0.95
    assert 0.25 < avg(slow_db, "frontend", fmt.ERROR_RATE, AFTER) < 0.35
    for service in SERVICES:
        assert avg(slow_db, service, fmt.ERROR_RATE, BEFORE) < 0.02, service


def test_latency_fault_leaves_other_paths_untouched(slow_db: SimRun) -> None:
    for service in ("auth", "catalog", "catalog-db"):
        assert avg(slow_db, service, fmt.ERROR_RATE, AFTER) < 0.02, service
        before = avg(slow_db, service, fmt.LATENCY_P50, BEFORE)
        assert avg(slow_db, service, fmt.LATENCY_P50, AFTER) == pytest.approx(before, rel=0.1)


def test_latency_fault_starves_the_second_caller(slow_db: SimRun) -> None:
    # checkout fails at cart (fail fast), so it stops calling payments altogether.
    assert avg(slow_db, "payments", fmt.THROUGHPUT, BEFORE) > 10
    assert avg(slow_db, "payments", fmt.THROUGHPUT, AFTER) < 1


def test_error_fault_spreads_with_the_expected_probabilities() -> None:
    run = simulate(Fault("error", "payments-db", at="+60s", strength=0.3))
    expected = {"cart": 0.30, "payments": 0.30, "checkout": 0.51, "frontend": 0.3 * 0.51}
    for service, rate in expected.items():
        assert avg(run, service, fmt.ERROR_RATE, AFTER) == pytest.approx(rate, abs=0.06), service


def test_saturation_shows_a_trend_before_the_breach(healthy: SimRun) -> None:
    run = simulate(Fault("saturation", "catalog-db", at="+30s", strength=60))  # full at +90 s
    util = [avg(run, "catalog-db", fmt.UTILIZATION, (a, a + 10)) for a in (30, 40, 50)]
    assert util == sorted(util) and util[0] < util[-1]
    assert avg(run, "catalog-db", fmt.UTILIZATION, (0, 30)) < 0.4
    assert avg(run, "catalog-db", fmt.ERROR_RATE, (30, 85)) < 0.02  # no breach yet
    healthy_p50 = avg(healthy, "catalog-db", fmt.LATENCY_P50, (80, 90))
    assert avg(run, "catalog-db", fmt.LATENCY_P50, (80, 90)) > 5 * healthy_p50
    for service in ("catalog-db", "catalog", "frontend"):  # every request needs the catalog
        assert avg(run, service, fmt.ERROR_RATE, (92, 120)) > 0.99, service


def test_regression_is_quiet_but_measurable(healthy: SimRun) -> None:
    run = simulate(Fault("regression", "payments-db"))  # 30% slower from the start
    ratio = avg(run, "payments-db", fmt.LATENCY_P50, (0, 120)) / avg(
        healthy, "payments-db", fmt.LATENCY_P50, (0, 120)
    )
    assert ratio == pytest.approx(1.3, abs=0.05)
    for service in SERVICES:  # no errors anywhere: only a careful comparison can catch it
        assert avg(run, service, fmt.ERROR_RATE, (0, 120)) < 0.02, service


def test_ground_truth_is_saved_with_the_faults(slow_db: SimRun, tmp_path: Path) -> None:
    folder = slow_db.save(tmp_path / "incident")
    saved = json.loads((folder / fmt.GROUND_TRUTH_FILE).read_text())
    assert saved == slow_db.ground_truth
    (fault,) = saved["faults"]
    assert (fault["kind"], fault["service"], fault["params"]) == (
        "latency",
        "payments-db",
        {"added_ms": 850.0},
    )
    assert fault["start_ns"] - slow_db.meta["start_ns"] == 60 * 1_000_000_000


def test_same_seed_and_faults_give_the_same_run(slow_db: SimRun) -> None:
    again = simulate(Fault("latency", "payments-db", at="+60s"))
    assert (again.metric_rows, again.spans) == (slow_db.metric_rows, slow_db.spans)


@pytest.mark.parametrize(
    ("fault", "message"),
    [(Fault("latency", "ghost"), "unknown service"), (Fault("error", "cart", at="5m"), "after")],
)
def test_run_rejects_impossible_faults(fault: Fault, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        simulate(fault)
