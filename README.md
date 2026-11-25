# Tracehound

**An offline, dependency-graph root-cause engine for distributed systems.**
Tracehound reads recorded metrics and traces, ranks the most likely root cause with the evidence
behind it, and catches performance regressions before they ship. Pure Python, no model download,
no API key, benchmarked on a built-in fault simulator.

[![CI](https://github.com/shanAweb/tracehound/actions/workflows/ci.yml/badge.svg)](https://github.com/shanAweb/tracehound/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> **Status: pre-alpha. Steps 1 and 2 of the roadmap are done: project skeleton, CI, and a
> fault-injection simulator that produces labelled incidents.**
> Tracehound is being built in small, tested, separately-committed steps. Anything marked
> *planned* below does not work yet. The [Roadmap](#roadmap) shows exactly what exists today.

---

## Contents

1. [Why Tracehound](#why-tracehound)
2. [The three modes](#the-three-modes)
3. [How it works](#how-it-works)
4. [The built-in simulator](#the-built-in-simulator)
5. [Usage](#usage)
6. [Input format: the incident folder](#input-format-the-incident-folder)
7. [How quality is measured](#how-quality-is-measured)
8. [Installation](#installation)
9. [Development](#development)
10. [Project layout](#project-layout)
11. [Roadmap](#roadmap)
12. [Out of scope for v0](#out-of-scope-for-v0)
13. [License](#license)

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

## The built-in simulator

Real multi-service incident data with a *known* cause is hard to get, so Tracehound ships its own
source. The simulator runs synthetic traffic through a small microservice system and plants
faults in it. Because we planted them, the true cause is known. That makes accuracy
measurable, makes the benchmark reproducible, and gives every reader a demo that needs none of
their own data.

**The `shop` system** has 8 services. Arrows mean "calls", and checkout is called on 30% of requests:

```text
frontend ─┬─> auth
          ├─> catalog ──> catalog-db
          └─> checkout (30%) ─┬─> cart ─────> payments-db
                              └─> payments ─> payments-db
```

`payments-db` has two callers, so a fault there creates victims along two paths.

**How one request is simulated:**

| Rule | Detail |
|---|---|
| Arrivals | Poisson process at the requested `rps`, entering at `frontend`. |
| Own processing time | Lognormal around each service's median (`base_ms`, jitter sigma 0.25), split half before and half after its calls. |
| Calls | Made one after another, in topology order. A span's duration is its own time plus its callees' time. |
| Errors | Each service fails by itself with probability `error_rate` (0.1% by default). A failure propagates to the caller, which stops making further calls. |
| Timeouts | Each call has a timeout. If the callee is slower, the caller gives up and fails, while the callee's own span keeps running, as in real systems. Healthy `shop` latencies are at least 5x below every timeout. |
| Metrics | Computed from **every** request, per service, per interval (default 1 s): p50/p95/p99 latency, error rate, throughput, utilization. |
| Utilization | Requests in flight ÷ the service's `capacity` (Little's law), plus any pool share held by a saturation leak, capped at 1.0 like a real pool gauge. Every service reports it, so its presence never gives away the faulty one. Capacities are sized for about 50 rps (healthy utilization 0.2-0.35); higher rps only raises the gauge, without queueing. |
| Traces | **Head-sampled** (default 10%): a request's whole trace is kept or dropped. |
| Window | The run records spans that *start* inside `[start, start + duration)`, like an export cut at end time. |
| Determinism | One seeded generator (`random.Random(seed)`) drives everything. The same seed gives byte-identical files. |

**Measured** (macOS x86_64, Python 3.12, `duration="10m", rps=50, seed=7`):

| Quantity | Value |
|---|---|
| Requests simulated | 29,721 (Poisson mean 30,000) |
| Traces kept | 2,927 (9.85%) with 15,679 spans, 5.36 spans per trace |
| Simulation time | 0.98 s (best of 3), plus 0.16 s to write the files |
| Folder size | 5.0 MB (3.8 MB traces, 1.2 MB metrics) |

### Planting faults

```python
from tracehound.sim import Fault

Fault("latency", service="payments-db", at="+4m")  # slows down from 4 min after start
Fault("error", service="cart", at="+2m", duration="1m", strength=0.5)  # fails 50% for 1 min
```

`at` is the offset from the start of the run (`0`, `90`, `"4m"` or `"+4m"`). `duration` defaults to
"until the run ends". `strength` defaults per kind:

| Kind | `strength` means | Default | What it models |
|---|---|---|---|
| `latency` | extra own processing time, in ms | 850 | a slow dependency (the spec's "40 ms -> 900 ms") |
| `error` | chance a request fails inside the service | 0.3 | a bad deploy or a failing dependency |
| `saturation` | seconds until the service's pool is exhausted | 300 | a connection or memory leak: requests queue as the pool fills (own time x 1/(1 - leaked), at most 20x), then every request is rejected |
| `regression` | multiplier on own processing time | 1.3 | a new version that is quietly slower (for Guard) |

A fault is applied when a service *starts* handling a request. Several faults can be active at
once: added latencies sum, multipliers multiply, and the highest error rate wins.

**What a fault looks like from the outside.** Measured on `shop` (2 min at 50 rps, seed 3; latency and
error faults at +60 s, averaged over +65 s to +115 s). Each row is checked by
`tests/sim/test_sim_propagation.py`:

| Planted fault | Root cause | Victims (error rate after onset) | Untouched |
|---|---|---|---|
| `latency` in payments-db | p50 40 -> 904 ms | cart 0.99, checkout 1.00, frontend 0.31; payments traffic drops 14.4 -> 0.14 rps (checkout fails before calling it) | auth, catalog, catalog-db |
| `error` 0.3 in payments-db | errors 0.31 | cart 0.30, payments 0.32, checkout 0.53 (expected 1 - 0.7² = 0.51), frontend 0.16 | auth, catalog, catalog-db |
| `saturation` in catalog-db (60 s to exhaustion, from +30 s) | utilization 0.30 -> 0.39 -> 0.62 -> 0.90 -> 1.00 over +30 s to +70 s; p50 6 -> 80 ms; then 100% errors from +90 s | catalog 1.00, frontend 1.00 | checkout path (never reached) |
| `regression` x1.3 in payments-db | p50 x1.30 | none: the highest error rate anywhere is 0.005, so only a baseline comparison reveals it | everything |

## Usage

### Works today: simulate a system, plant a fault, save the telemetry

```python
from tracehound.sim import Fault, System

system = System.example("shop")

healthy = system.run(duration="10m", rps=50, seed=7)  # trace_sample_rate=0.1, metric_interval_s=1.0
print(healthy.n_requests, len(healthy.spans))  # 29721 15679
healthy.save("runs/shop_seed7/")  # meta.json, metrics.csv, traces.jsonl, ground_truth.json

incident = system.run(
    duration="10m", rps=50, seed=7, faults=[Fault("latency", service="payments-db", at="+4m")]
)
incident.save("incidents/payments_latency/")  # ground_truth.json records the planted cause
```

### Planned API

> *Planned.* This is the target public surface, built step by step; see the [Roadmap](#roadmap).

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
| `utilization` | fraction 0-1 of capacity in use | up |
| anything else (e.g. `db_connections`) | as named | either (two-sided) |

Rules for `metrics.csv`:
- `timestamp_ms` is the **start** of the interval. A request counts in the interval in which it started.
- An interval with no requests has only `throughput_rps = 0` and `utilization`. Latency and error
  rate are left out, because they are undefined for zero requests and are never invented.
- Values are rounded to 4 decimals, with trailing zeros dropped (`3`, `41.2`, `0.0012`).

**`traces.jsonl`** has one span per line, sorted by `start_ns`, then `span_id`:

```json
{"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "span_id": "00f067aa0ba902b7", "parent_span_id": null, "service": "checkout", "name": "POST /checkout", "start_ns": 1767225600123000000, "end_ns": 1767225600187000000, "status": "ok"}
```

`status` is `"ok"` or `"error"`. All times are integer Unix epochs whose unit is in the field name
(`_ns` = nanoseconds, `_ms` = milliseconds).

**`ground_truth.json`** (simulator only) records the seed and every planted fault, sorted by onset.
A healthy run has `"faults": []`.

```json
{
  "faults": [
    {
      "end_ns": 1767226200000000000,
      "kind": "latency",
      "params": {"added_ms": 850.0},
      "service": "payments-db",
      "start_ns": 1767225840000000000
    }
  ],
  "seed": 7
}
```

`params` holds one entry named after the kind: `added_ms` (latency), `error_rate` (error),
`time_to_exhaustion_s` (saturation) or `latency_factor` (regression).

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
pytest                  # tests, docstring examples (doctests) and the repository rules
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
│   ├── _format.py       incident-folder constants shared by every writer and reader
│   ├── ingest/          stage 1: incident folder -> typed data
│   ├── detect/          stage 2: anomaly + onset detection (robust z, CUSUM)
│   ├── correlate/       stage 3: group anomalies into one incident
│   ├── graph/           stage 4: build call graph, rank root causes
│   ├── report/          stage 5: JSON + text renderers
│   ├── sim/             fault-injection simulator (ground-truth incidents)
│   │   ├── topology.py    Service, Call, Topology (validated: acyclic, all reachable)
│   │   ├── examples.py    ready-made systems, e.g. "shop"
│   │   ├── faults.py      Fault (latency, error, saturation, regression) and FaultPlan
│   │   ├── request.py     one request -> one span per service (latency, errors, timeouts)
│   │   ├── metrics.py     spans -> per-interval p50/p95/p99, error rate, throughput, utilization
│   │   ├── writer.py      deterministic incident-folder writer
│   │   ├── system.py      System.run(): traffic, sampling, recording window -> SimRun
│   │   └── units.py       "10m" / "30s" duration parsing
│   └── bench/           benchmark harness -> results.json
├── tests/               unit tests per stage + end-to-end scenarios (tests/sim/ for the simulator)
└── pyproject.toml       packaging + tool configuration
```

## Roadmap

Each step is built, tested and pushed on its own.

| Step | What | Done when | Status |
|---|---|---|---|
| 1 | Project skeleton, tooling, CI, format spec | Installs; lint, types and tests pass | ✅ done |
| 2a | Simulator: healthy traffic | Same seed -> byte-identical folder, also across processes | ✅ done |
| 2b | Simulator: fault injection | 4 fault types; faults spread to callers; ground truth written | ✅ done |
| 3 | Ingest + Detect | Folder round-trips; detector accuracy and onset error measured | ⏳ next |
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
