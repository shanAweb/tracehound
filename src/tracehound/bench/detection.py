"""Score Detect against ground truth: false alarms, recall of the planted cause, onset error.

Every scenario goes through the same path as a user's data: simulate, save to a folder, load,
detect. Run it with ``python -m tracehound.bench.detection --help``.

- **Flagged** (healthy runs): the run has at least one anomaly.
- **Cause found** (faulted runs): the faulted service has an anomaly whose onset lies between
  one metric interval plus 5 s before the fault and the fault's end. (The metric interval
  that contains the fault's start begins up to one interval before it.)
- **Onset error**: the earliest such onset minus the fault's start. It is reported separately
  for step faults (latency, error, regression) and for ramps (saturation, which builds up
  gradually).
- **Early anomalies**: anomalies in any service with an onset before that window.
"""

import argparse
import json
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field

from tracehound._format import NS_PER_S
from tracehound.bench.scenarios import Group, Scenario, Split, make_scenarios
from tracehound.bench.stats import summary, wilson
from tracehound.detect import DetectConfig, detect
from tracehound.ingest import load
from tracehound.sim import System

EARLY_SLACK_S = 5.0


@dataclass(frozen=True)
class Setup:
    rps: float = 50.0
    metric_interval_s: float = 1.0
    config: DetectConfig = field(default_factory=DetectConfig)


@dataclass(frozen=True)
class Outcome:
    """One scenario, scored."""

    seed: int
    group: Group
    kind: str | None
    service: str | None
    false_signals: tuple[str, ...]  # healthy runs: "service signal" of every anomaly
    cause_found: bool
    onset_error_s: float | None
    early: int
    detect_s: float


def run_scenario(scenario: Scenario, setup: Setup) -> Outcome:
    faults = [scenario.fault] if scenario.fault else []
    run = System.example("shop").run(
        duration=scenario.duration_s, rps=setup.rps, seed=scenario.seed, faults=faults,
        metric_interval_s=setup.metric_interval_s,
    )  # fmt: skip
    with tempfile.TemporaryDirectory(prefix="tracehound-bench-") as folder:
        incident = load(run.save(folder))
    started = time.perf_counter()
    anomalies = detect(incident, setup.config).anomalies
    detect_s = time.perf_counter() - started
    fault = scenario.fault
    if fault is None or incident.ground_truth is None:
        found = tuple(f"{a.service} {a.signal}" for a in anomalies)
        return Outcome(scenario.seed, scenario.group, None, None, found, False, None, 0, detect_s)
    (planted,) = incident.ground_truth.faults
    earliest_ok = planted.start_ns - round((setup.metric_interval_s + EARLY_SLACK_S) * NS_PER_S)
    hits = [
        a.onset_ns
        for a in anomalies
        if a.service == planted.service and earliest_ok <= a.onset_ns <= planted.end_ns
    ]
    error_s = (min(hits) - planted.start_ns) / NS_PER_S if hits else None
    early = sum(a.onset_ns < earliest_ok for a in anomalies)
    return Outcome(
        scenario.seed, scenario.group, fault.kind, fault.service, (), bool(hits), error_s, early,
        detect_s,
    )  # fmt: skip


def _run(args: tuple[Scenario, Setup]) -> Outcome:
    return run_scenario(*args)


def run_all(scenarios: Sequence[Scenario], setup: Setup, workers: int = 1) -> list[Outcome]:
    """Score every scenario, in order. ``workers > 1`` runs them in parallel processes."""
    jobs = [(s, setup) for s in scenarios]
    if workers <= 1:
        return [_run(job) for job in jobs]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_run, jobs, chunksize=4))


def summarize(outcomes: Sequence[Outcome]) -> dict[str, object]:
    """Group results by scenario group, with 95% Wilson intervals on every rate."""
    result: dict[str, object] = {}
    healthy = [o for o in outcomes if o.group == "healthy"]
    if healthy:
        flagged = sum(bool(o.false_signals) for o in healthy)
        signals = Counter(s for o in healthy for s in o.false_signals)
        result["healthy"] = {
            "runs": len(healthy),
            "flagged": flagged,
            "flagged_ci95": [round(v, 3) for v in wilson(flagged, len(healthy))],
            "false_signals": dict(sorted(signals.items())),
        }
    for group in ("faulted", "ending"):
        rows = [o for o in outcomes if o.group == group]
        if rows:
            result[group] = _summarize_faulted(rows)
    times = sorted(o.detect_s for o in outcomes)
    result["detect_ms_median"] = round(1000 * times[len(times) // 2], 1) if times else None
    return result


def _summarize_faulted(rows: Sequence[Outcome]) -> dict[str, object]:
    found = sum(o.cause_found for o in rows)
    kinds = sorted({o.kind or "" for o in rows})
    by_kind = {k: f"{sum(o.cause_found for o in rows if o.kind == k)}/"
                  f"{sum(o.kind == k for o in rows)}" for k in kinds}  # fmt: skip
    missed = Counter(f"{o.kind} {o.service}" for o in rows if not o.cause_found)
    step = [o.onset_error_s for o in rows if o.onset_error_s is not None and o.kind != "saturation"]
    ramp = [o.onset_error_s for o in rows if o.onset_error_s is not None and o.kind == "saturation"]
    return {
        "incidents": len(rows),
        "cause_found": found,
        "cause_found_ci95": [round(v, 3) for v in wilson(found, len(rows))],
        "by_kind": by_kind,
        "missed": dict(sorted(missed.items())),
        "onset_error_s": {"step": summary(step), "ramp": summary(ramp)},
        "early_anomalies": sum(o.early for o in rows),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tracehound.bench.detection")
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--healthy", type=int, default=100)
    parser.add_argument("--faulted", type=int, default=100)
    parser.add_argument("--ending", type=int, default=60)
    parser.add_argument("--duration", type=float, default=600.0, help="seconds per run")
    parser.add_argument("--interval", type=float, default=1.0, help="metric interval, seconds")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    split: Split = args.split
    counts: dict[Group, int] = {
        "healthy": args.healthy,
        "faulted": args.faulted,
        "ending": args.ending,
    }
    scenarios: list[Scenario] = []
    for group, count in counts.items():
        scenarios += make_scenarios(split, group, count, duration_s=args.duration)
    setup = Setup(metric_interval_s=args.interval)
    outcomes = run_all(scenarios, setup, args.workers)
    report = {"split": split, "setup": asdict(setup), **summarize(outcomes)}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
