"""Benchmark scenarios, statistics and the detection scorer, on small fast runs."""

import json

import pytest

from tracehound.bench.detection import Outcome, Setup, main, run_all, summarize
from tracehound.bench.scenarios import make_scenarios
from tracehound.bench.stats import summary, wilson
from tracehound.sim import Fault


def test_scenarios_are_deterministic_and_splits_do_not_overlap() -> None:
    dev = make_scenarios("dev", "faulted", 20)
    assert dev == make_scenarios("dev", "faulted", 20)
    test_seeds = {s.seed for s in make_scenarios("test", "faulted", 20)}
    assert not test_seeds & {s.seed for s in dev}
    assert {s.fault.kind for s in dev if s.fault} == {
        "latency",
        "error",
        "saturation",
        "regression",
    }


def test_fault_start_and_length_follow_the_rules() -> None:
    for s in make_scenarios("dev", "ending", 30, duration_s=600):
        assert isinstance(s.fault, Fault) and isinstance(s.fault.at, float)
        assert 240 <= s.fault.at <= 420 and s.fault.duration is not None
        assert 60 <= float(s.fault.duration) <= 180
    assert all(s.fault is None for s in make_scenarios("test", "healthy", 5))
    assert all(s.fault and s.fault.duration is None for s in make_scenarios("dev", "faulted", 5))


def test_bad_scenario_requests_are_rejected() -> None:
    with pytest.raises(ValueError):
        make_scenarios("prod", "healthy", 3)  # type: ignore[arg-type]


def test_wilson_interval() -> None:
    assert wilson(0, 59)[1] == pytest.approx(0.0611, abs=1e-4)  # 0/59 bounds a rate at 6.1%
    low, high = wilson(50, 100)
    assert low == pytest.approx(1 - high) and low < 0.5 < high
    with pytest.raises(ValueError):
        wilson(3, 2)


def test_summary_of_values() -> None:
    assert summary([]) == {"n": 0}
    assert summary([-1.0, 0.0, 2.0, 10.0]) == {
        "n": 4,
        "median": 1.0,
        "p90_abs": 7.6,
        "max_abs": 10.0,
    }


def test_scoring_a_small_mixed_set() -> None:
    scenarios = [
        *make_scenarios("dev", "healthy", 2, duration_s=180),
        *[s for s in make_scenarios("dev", "faulted", 12, duration_s=180)
          if s.fault and s.fault.kind in ("latency", "error")][:3],
    ]  # fmt: skip
    outcomes = run_all(scenarios, Setup(rps=40))
    by_seed = {o.seed: o for o in outcomes}
    assert [o.seed for o in outcomes] == [s.seed for s in scenarios]
    for s in scenarios[2:]:
        outcome = by_seed[s.seed]
        assert outcome.cause_found, s
        assert outcome.onset_error_s is not None and abs(outcome.onset_error_s) <= 1.0
    report = summarize(outcomes)
    assert report["healthy"] == {
        "runs": 2, "flagged": 0, "flagged_ci95": [0.0, 0.658], "false_signals": {},
    }  # fmt: skip


def test_summarize_counts_misses_and_kinds() -> None:
    def outcome(kind: str, found: bool, error: float | None) -> Outcome:
        return Outcome(1, "faulted", kind, "cart", (), found, error, 0, 0.01)

    report = summarize([outcome("latency", True, 0.5), outcome("regression", False, None)])
    faulted = report["faulted"]
    assert isinstance(faulted, dict)
    assert faulted["by_kind"] == {"latency": "1/1", "regression": "0/1"}
    assert faulted["missed"] == {"regression cart": 1}


def test_command_line_prints_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--split", "dev", "--healthy", "1", "--faulted", "0", "--ending", "0",
                 "--duration", "120"]) == 0  # fmt: skip
    report = json.loads(capsys.readouterr().out)
    assert report["split"] == "dev" and report["healthy"]["runs"] == 1
