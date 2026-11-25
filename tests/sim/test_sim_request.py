"""The single-request model: span tree shape, timeouts, error propagation."""

import random
from collections.abc import Callable

from tracehound.sim import Topology, example
from tracehound.sim.request import RequestSimulator, SpanRecord, ms_to_ns

TopologyFactory = Callable[..., Topology]


def run_one(topology: Topology, seed: int = 0) -> list[SpanRecord]:
    return RequestSimulator(topology, random.Random(seed)).simulate(0, sampled=True)


def by_service(spans: list[SpanRecord]) -> dict[str, SpanRecord]:
    return {s.service: s for s in spans}


def test_span_tree_matches_the_topology() -> None:
    topo = example("shop")
    sim = RequestSimulator(topo, random.Random(1))
    edges = set(topo.edges())
    for _ in range(300):
        spans = sim.simulate(0, sampled=True)
        ids = {s.span_id: s for s in spans}
        roots = [s for s in spans if s.parent_span_id is None]
        assert len(roots) == 1 and roots[0].service == topo.entry
        assert len({s.trace_id for s in spans}) == 1
        assert len(spans[0].trace_id) == 32 and all(len(s.span_id) == 16 for s in spans)
        for child in spans:
            if child.parent_span_id is None:
                continue
            parent = ids[child.parent_span_id]
            assert (parent.service, child.service) in edges
            # Healthy shop never times out, so every child lies inside its parent.
            assert parent.start_ns <= child.start_ns and child.end_ns <= parent.end_ns


def test_unsampled_requests_carry_no_ids() -> None:
    spans = RequestSimulator(example("shop"), random.Random(2)).simulate(0, sampled=False)
    assert spans and all(s.trace_id == "" and s.span_id == "" for s in spans)


def test_timing_is_exact_without_jitter(chain: TopologyFactory) -> None:
    spans = by_service(run_one(chain(a_ms=10, b_ms=20)))
    assert spans["b"].end_ns - spans["b"].start_ns == ms_to_ns(20)
    assert spans["a"].end_ns - spans["a"].start_ns == ms_to_ns(10 + 20)
    assert spans["b"].start_ns == ms_to_ns(5)  # half of a's own time happens before the call
    assert not spans["a"].error and not spans["b"].error


def test_timeout_fails_the_caller_but_not_the_callee(chain: TopologyFactory) -> None:
    spans = by_service(run_one(chain(a_ms=10, b_ms=1000, timeout_ms=100)))
    a, b = spans["a"], spans["b"]
    assert a.error and not b.error
    assert a.end_ns - a.start_ns == ms_to_ns(10 + 100)  # a waited exactly the timeout
    assert b.end_ns - b.start_ns == ms_to_ns(1000)  # b kept working after a gave up
    assert b.end_ns > a.end_ns


def test_callee_error_propagates_and_stops_further_calls(chain: TopologyFactory) -> None:
    spans = by_service(run_one(chain(b_error=1.0, with_c=True)))
    assert spans["b"].error and spans["a"].error
    assert "c" not in spans  # fail fast: a never called c


def test_service_failing_by_itself_makes_no_calls(chain: TopologyFactory) -> None:
    spans = run_one(chain(a_error=1.0))
    assert [s.service for s in spans] == ["a"] and spans[0].error


def test_call_probability_is_respected() -> None:
    topo = example("shop")  # frontend -> checkout with probability 0.3
    sim = RequestSimulator(topo, random.Random(3))
    n = 5000
    hits = sum(any(s.service == "checkout" for s in sim.simulate(0, False)) for _ in range(n))
    sigma = (0.3 * 0.7 / n) ** 0.5
    assert abs(hits / n - 0.3) < 4 * sigma


def test_same_seed_gives_identical_spans() -> None:
    def spans(seed: int) -> list[list[SpanRecord]]:
        sim = RequestSimulator(example("shop"), random.Random(seed))
        return [sim.simulate(i * 1000, True) for i in range(50)]

    assert spans(5) == spans(5)
    assert spans(5) != spans(6)
