# Tracehound

**An offline, dependency-graph root-cause engine for distributed systems.**
Tracehound reads recorded metrics and traces, ranks the most likely root cause with the evidence
behind it, and catches performance regressions before they ship. Pure Python, no model download,
no API key, benchmarked on a built-in fault simulator.

[![CI](https://github.com/shanAweb/tracehound/actions/workflows/ci.yml/badge.svg)](https://github.com/shanAweb/tracehound/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> **Status: pre-alpha, Step 1 of the roadmap is done (project skeleton, tooling, CI).**
> Tracehound is being built in small, tested, separately-committed steps. Anything marked
> *planned* below does not work yet. The [Roadmap](#roadmap) shows exactly what exists today.

---

## Contents

1. [Why Tracehound](#why-tracehound)
2. [The three modes](#the-three-modes)
3. [How it works](#how-it-works)
4. [Usage (planned API)](#usage-planned-api)
5. [Input format: the incident folder](#input-format-the-incident-folder)
6. [How quality is measured](#how-quality-is-measured)
7. [Installation](#installation)
8. [Development](#development)
9. [Project layout](#project-layout)
10. [Roadmap](#roadmap)
11. [Out of scope for v0](#out-of-scope-for-v0)
12. [License](#license)

---

## Why Tracehound

When a distributed system misbehaves, symptoms appear everywhere at once: a dozen services report
errors and high latency within seconds. The on-call engineer then plays detective: which service is
the **cause**, and which are just **victims** of it?

```text
checkout     error rate   0.00 -> 0.34    from 14:02:11   victim
cart         error rate   0.00 -> 0.29    from 14:02:09   victim
payments-db  latency      40ms -> 900ms   from 14:02:03   ROOT CAUSE: earliest, and the others call into it
```

Noticing that a number looks wrong (anomaly detection) is a solved, crowded problem. Tracehound's
contribution is the step after it, **causal localization**: it rebuilds the service dependency
graph from traces and ranks which anomalous service best explains all the others.

What makes it easy to adopt:

| Property | What it means for you |
|---|---|
| **Offline-first** | Works on recorded telemetry in a folder. No Kubernetes, agents or infrastructure. |
| **No model, no key** | Classic statistics + graph algorithms, computed in-process. Nothing to download. |
| **A library, not a SaaS** | `import tracehound` inside CI, a notebook, or your own tooling. |
| **Explains itself** | Every ranked cause carries its evidence: timing, magnitude, which victims it explains. |
| **Deterministic** | Same input -> byte-identical report, every run. |
| **Honest numbers** | Accuracy is measured on incidents with known causes and reported with confidence intervals, false alarms included. |

## The three modes

One engine, exposed at three moments in a system's life. The modes differ only in what they
compare against and what they emit.

| Mode | When | Question it answers | Version |
|---|---|---|---|
| **Guard** | Before you ship (CI / load test) | "Did my change make it measurably worse than the known-good baseline?" | v0 |
| **Explain** | After it breaks (post-incident) | "Across everything that looks broken, what is the most likely root cause?" | v0 |
| **Watch** | While it runs (early warning) | "Is a visible trend heading for a limit, and how long until it hits?" | v1 |

Watch only extrapolates trends that are already visible (for example, a connection pool filling
up). It never claims to predict incidents with unknown causes.

## How it works

All modes run the same five-stage pipeline. Each stage is its own subpackage and is tested on its own.

```text
incident folder --> 1 Ingest --> 2 Detect --> 3 Correlate --> 4 Localize --> 5 Report
(metrics + traces)  typed data   anomalies +   one incident    ranked causes   JSON + text
                                 onset times   time window     + evidence
```

| Stage | Does | Technique (no model, no key) |
|---|---|---|
| 1 Ingest | Reads metrics and trace spans into typed, columnar data | stdlib `csv`/`json` + numpy |
| 2 Detect | Flags anomalous signals against their own pre-incident baseline and estimates **when** each change began | robust z-score (median/MAD) + CUSUM change-point |
| 3 Correlate | Groups anomalies that begin close together into one incident | 1-D gap clustering on onset times |
| 4 Localize | Builds the service graph from traces and ranks the most likely cause | networkx + personalized PageRank + timing |
| 5 Report | Emits ranked hypotheses with evidence | deterministic JSON + text renderer |

### How a root cause is ranked

1. **Build the call graph.** In a trace, a span whose parent span belongs to another service is a
   call. Aggregated over many traces this gives a directed graph: `caller -> callee`.
2. **Faults travel the other way.** A slow or failing *callee* makes its *callers* slow or fail. So
   blame flows from each victim towards the services it calls.
3. **Score each anomalous service** on three signals:
   - **onset**: it started misbehaving earliest. This is the estimated change-point, not the
     moment an alarm fired, because large changes trip alarms sooner.
   - **magnitude**: how strong its anomaly is.
   - **coverage**: how many anomalous callers its fault explains.
4. **Propagate** with a personalized PageRank walk from victims toward the services they call,
   which concentrates blame on the service that explains the most damage.
5. **Rank and explain.** The output is the top-k services, each with a `score` (its share of the
   blame, summing to 1 across candidates) and the concrete evidence behind it.

> **Vocabulary.** Tracehound uses *caller*, *callee*, *victim* and *root cause*. It avoids
> "upstream" and "downstream", which mean opposite things in call order and in fault order:
> payments-db is *downstream* of cart in call order (cart calls it) but *upstream* in fault
> order (its failure flows to cart).

## Usage (planned API)

> *Planned.* This is the target public surface. It is built step by step; see the [Roadmap](#roadmap).

```python
import tracehound as th

# Explain: post-incident root cause
incident = th.load("incidents/payments_latency/")
report = th.explain(incident)
print(report.top(3))  # ranked causes + evidence
report.to_json("report.json")

# Guard: fail a CI build on a reliability regression
result = th.guard(candidate="runs/pr_241/", baseline="runs/main/")  # baseline: folder of >= 3 runs
assert result.ok, result.regressions
```

Generate a labelled incident with the built-in simulator. The fault is planted, so the true cause is known:

```python
from tracehound.sim import System, Fault

system = System.example("shop")  # checkout, cart, payments-db, auth, ...
incident = system.run(
    duration="10m",
    rps=50,
    seed=7,
    faults=[Fault("latency", service="payments-db", at="+4m")],
)
incident.save("incidents/payments_latency/")  # metrics + traces + ground_truth.json
```

Example Explain output (illustrative):

```text
INCIDENT incidents/payments_latency   window 14:02:00-14:04:30
#1 payments-db   score 0.74   <- ROOT CAUSE
   onset 14:02:03 (earliest) · latency p95 40ms -> 900ms · explains 4/4 anomalous callers
#2 cart          score 0.17
   onset 14:02:09 · calls payments-db (likely victim)
#3 checkout      score 0.09
   onset 14:02:11 · calls cart (likely victim)
```

## Input format: the incident folder

Every mode reads the same folder format. The simulator writes it, and Guard's load-test runs use
it too.

```text
my_incident/
  meta.json          required  - time range and sampling information
  metrics.csv        required  - one row per (time, service, metric) sample
  traces.jsonl       required  - one span per line
  ground_truth.json  optional  - the planted cause (simulator output only)
```

**`meta.json`**

```json
{
  "format_version": 1,
  "start_ns": 1767225600000000000,
  "end_ns": 1767226200000000000,
  "metric_interval_s": 1.0,
  "trace_sample_rate": 0.1,
  "source": "tracehound.sim"
}
```

**`metrics.csv`** has long-format rows sorted by `service`, `metric`, `timestamp_ms`:

```csv
timestamp_ms,service,metric,value
1767225600000,payments-db,latency_p95_ms,41.2
1767225601000,payments-db,latency_p95_ms,39.8
```

| Standard metric | Unit | Bad direction |
|---|---|---|
| `latency_p50_ms`, `latency_p95_ms`, `latency_p99_ms` | milliseconds | up |
| `error_rate` | fraction 0-1 | up |
| `throughput_rps` | requests / second | down |
| anything else (e.g. `db_connections`) | as named | either (two-sided) |

**`traces.jsonl`** has one span per line, sorted by `start_ns`, then `span_id`:

```json
{"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "span_id": "00f067aa0ba902b7", "parent_span_id": null, "service": "checkout", "name": "POST /checkout", "start_ns": 1767225600123000000, "end_ns": 1767225600187000000, "status": "ok"}
```

`status` is `"ok"` or `"error"`. All times are integer Unix epochs whose unit is in the field name
(`_ns` = nanoseconds, `_ms` = milliseconds).

**`ground_truth.json`** (simulator only):

```json
{"seed": 7, "faults": [{"kind": "latency", "service": "payments-db", "start_ns": 1767225840000000000, "params": {"added_ms": 850}}]}
```

*Planned:* an adapter for OpenTelemetry OTLP-JSON exports, so real collector output can be used directly.

## How quality is measured

Every metric is computed on simulated incidents where the true cause is known. Numbers come from
`tracehound.bench` into `results.json` and are never typed by hand.

| Mode | Metric | Target (v0) | Current |
|---|---|---|---|
| Explain | Top-1 accuracy (true cause ranked #1) | >= 0.75 | not measured yet |
| Explain | Top-3 accuracy | >= 0.90 | not measured yet |
| Explain | Mean reciprocal rank | >= 0.80 | not measured yet |
| Guard | Regression recall | >= 0.90 | not measured yet |
| Guard | False-positive rate on clean runs | <= 0.05 | not measured yet |
| Engine | Time to localize one incident | report only | not measured yet |

The protocol keeps these numbers honest:

- **Held-out seeds.** Parameters are tuned on *dev* seeds. The reported scores come from separate *test* seeds.
- **Confidence intervals.** Every rate is reported with a 95% interval. With 120 incidents, an
  observed 0.78 could really be anywhere from 0.70 to 0.85, so a target is only "passed" when the
  interval supports it.
- **Enough samples.** About 300 incidents and at least 100 clean runs. Showing a false-positive
  rate <= 0.05 at 95% confidence needs at least 59 clean runs with zero false alarms.
- **Hard cases on purpose.** The simulator can add retries, hidden shared dependencies, unrelated
  anomalies, trace sampling and clock skew, and accuracy is reported for each of these.

## Installation

Tracehound is not on PyPI yet (*planned:* `pip install tracehound`). To install from source:

```bash
git clone https://github.com/shanAweb/tracehound.git
cd tracehound
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Requirements: Python **3.12+**. Core dependencies: `numpy`, `scipy`, `networkx`.
Optional extras: `pip install -e ".[ml]"` (scikit-learn detectors) and `pip install -e ".[pandas]"`
(DataFrame helpers).

## Development

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip               # dependency groups need pip >= 25.1
pip install -e . --group dev            # pytest, ruff, mypy

ruff check .            # lint
ruff format --check .   # formatting
mypy                    # strict type checking
pytest                  # tests (including the repository rules)
```

CI runs the same four checks on Python 3.12, 3.13 and 3.14, on Linux and macOS.

**Code rules** (enforced by CI, not by convention):

- **No code file over 200 lines.** `tests/test_repo_rules.py` fails the build if one is.
- Lines of at most 100 characters, fully type-annotated (`mypy --strict`).
- One subpackage per pipeline stage, and each one is tested on its own.
- The core package never imports the optional extras (`tests/test_package.py`).
- Determinism: sorted collections, seeded randomness, rounded floats, sorted JSON keys.

## Project layout

```text
tracehound/
├── src/tracehound/
│   ├── __init__.py      public API: load(), explain(), guard()  (built step by step)
│   ├── ingest/          stage 1: incident folder -> typed data
│   ├── detect/          stage 2: anomaly + onset detection (robust z, CUSUM)
│   ├── correlate/       stage 3: group anomalies into one incident
│   ├── graph/           stage 4: build call graph, rank root causes
│   ├── report/          stage 5: JSON + text renderers
│   ├── sim/             fault-injection simulator (ground-truth incidents)
│   └── bench/           benchmark harness -> results.json
├── tests/               unit tests per stage + end-to-end scenarios
└── pyproject.toml       packaging + tool configuration
```

## Roadmap

Each step is built, tested and pushed on its own.

| Step | What | Done when | Status |
|---|---|---|---|
| 1 | Project skeleton, tooling, CI, format spec | Installs; lint, types and tests pass | ✅ done |
| 2 | Simulator | Same seed -> byte-identical incident folder; 4 fault types | ⏳ next |
| 3 | Ingest + Detect | Folder round-trips; detector accuracy and onset error measured | planned |
| 4 | Graph + Localize | Top-1/Top-3/MRR with intervals on dev seeds; ablation table | planned |
| 5 | Explain report | Golden-file tests; identical bytes across processes | planned |
| 6 | Guard | Recall >= 0.90 and FPR <= 0.05 on held-out seeds | planned |
| 7 | Benchmark + scoreboard | `results.json` generates this README's numbers | planned |
| v1 | Watch mode | Lead time reported alongside false-alarm rate | later |

## Out of scope for v0

Left out on purpose, so the core ships first:

- **Watch mode**: live alerting needs careful false-alarm work. It comes in v1, once the core is proven.
- **Log parsing**: metrics and traces are enough to prove the approach.
- **Live agents, collectors and storage backends**: Tracehound stays offline, working on recorded data.
- **A UI**: the text and JSON report is the interface.

## License

[MIT](LICENSE) © 2026 Shan Asif
