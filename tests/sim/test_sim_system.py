"""End-to-end ``System.run``: traffic volume, sampling, determinism, argument checks."""

import pytest

from tracehound import _format as fmt
from tracehound.sim import SimRun, System

# 60 s at 50 rps: Poisson mean 3000, so 3 sigma = 3 * sqrt(3000) ~= 164 requests.
DURATION_S, RPS = 60, 50


@pytest.fixture(scope="module")
def run() -> SimRun:
    return System.example("shop").run(duration=f"{DURATION_S}s", rps=RPS, seed=11)


def test_request_count_is_poisson(run: SimRun) -> None:
    mean = DURATION_S * RPS
    assert abs(run.n_requests - mean) < 3 * mean**0.5


def test_trace_sampling_rate(run: SimRun) -> None:
    n_traces = len({s.trace_id for s in run.spans})
    sigma = (0.1 * 0.9 / run.n_requests) ** 0.5
    assert abs(n_traces / run.n_requests - 0.1) < 3 * sigma


def test_metrics_cover_every_request(run: SimRun) -> None:
    # Throughput sums to request counts per service; frontend sees every request that
    # started inside the window, while traces only hold the ~10% sample.
    frontend = sum(
        r.value for r in run.metric_rows if r.service == "frontend" and r.metric == fmt.THROUGHPUT
    )
    assert frontend == run.n_requests


def test_checkout_share_over_all_requests(run: SimRun) -> None:
    def total(service: str) -> float:
        rows = run.metric_rows
        return sum(r.value for r in rows if r.service == service and r.metric == fmt.THROUGHPUT)

    share = total("checkout") / total("frontend")
    assert abs(share - 0.3) < 3 * (0.3 * 0.7 / run.n_requests) ** 0.5


def test_spans_are_sorted_and_inside_the_window(run: SimRun) -> None:
    start, end = run.meta["start_ns"], run.meta["end_ns"]
    assert isinstance(start, int) and isinstance(end, int)
    keys = [(s.start_ns, s.span_id) for s in run.spans]
    assert keys == sorted(keys)
    assert all(start <= s.start_ns < end for s in run.spans)


def test_meta_and_ground_truth(run: SimRun) -> None:
    assert run.meta == {
        "format_version": 1,
        "start_ns": 1_767_225_600_000_000_000,
        "end_ns": 1_767_225_600_000_000_000 + DURATION_S * 1_000_000_000,
        "metric_interval_s": 1.0,
        "trace_sample_rate": 0.1,
        "source": "tracehound.sim",
    }
    assert run.ground_truth == {"seed": 11, "faults": []}


def test_same_seed_same_run_and_different_seed_different_run() -> None:
    system = System.example("shop")
    a, b, c = (system.run(duration="10s", rps=20, seed=s) for s in (3, 3, 4))
    assert (a.metric_rows, a.spans, a.n_requests) == (b.metric_rows, b.spans, b.n_requests)
    assert a.spans != c.spans


def test_full_sampling_keeps_every_trace() -> None:
    run = System.example("shop").run(duration="5s", rps=20, seed=1, trace_sample_rate=1.0)
    assert len({s.trace_id for s in run.spans}) == run.n_requests


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rps": 0},
        {"trace_sample_rate": 0.0},
        {"trace_sample_rate": 1.5},
        {"duration": "soon"},
        {"metric_interval_s": 0},
    ],
)
def test_invalid_arguments_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        System.example("shop").run(**kwargs)  # type: ignore[arg-type]
