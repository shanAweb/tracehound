"""Topology validation and the shop example."""

import pytest

from tracehound.sim import Call, Service, Topology, example


def svc(name: str) -> Service:
    return Service(name, f"op-{name}", base_ms=1.0)


def test_shop_example_shape() -> None:
    topo = example("shop")
    assert topo.entry == "frontend"
    assert len(topo.service_names) == 8
    assert len(topo.edges()) == 8
    callers_of_db = sorted(caller for caller, callee in topo.edges() if callee == "payments-db")
    assert callers_of_db == ["cart", "payments"]


def test_shop_healthy_latency_is_far_below_timeouts() -> None:
    # Median end-to-end time of a callee = its own time + its callees' (sequential calls).
    # A 5x margin keeps healthy runs free of timeouts, so only injected faults cause them.
    topo = example("shop")

    def median_total_ms(name: str) -> float:
        own = topo.services[name].base_ms
        return own + sum(median_total_ms(c.callee) for c in topo.calls_from(name))

    for caller in topo.service_names:
        for call in topo.calls_from(caller):
            assert median_total_ms(call.callee) * 5 < call.timeout_ms, (caller, call.callee)


def test_calls_keep_their_given_order() -> None:
    topo = Topology(
        "t", [svc("a"), svc("b"), svc("c")], [Call("a", "c"), Call("a", "b")], entry="a"
    )
    assert [c.callee for c in topo.calls_from("a")] == ["c", "b"]


@pytest.mark.parametrize(
    ("services", "calls", "entry", "message"),
    [
        (["a", "a"], [], "a", "duplicate"),
        (["a"], [], "zzz", "entry service"),
        (["a"], [("a", "ghost")], "a", "unknown service"),
        (["a", "b", "c"], [("a", "b"), ("b", "c"), ("c", "b")], "a", "cycle"),
        (["a", "b"], [("a", "b"), ("b", "a")], "a", "must not be called"),
        (["a", "b"], [], "a", "not reachable"),
    ],
)
def test_invalid_topologies_are_rejected(
    services: list[str], calls: list[tuple[str, str]], entry: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        Topology("bad", [svc(s) for s in services], [Call(a, b) for a, b in calls], entry)


@pytest.mark.parametrize(
    "kwargs",
    [{"base_ms": 0.0}, {"base_ms": 1.0, "jitter": -0.1}, {"base_ms": 1.0, "error_rate": 1.5}],
)
def test_invalid_services_are_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        Service("x", "op", **kwargs)


@pytest.mark.parametrize(
    "kwargs", [{"probability": 0.0}, {"probability": 1.1}, {"timeout_ms": 0.0}]
)
def test_invalid_calls_are_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        Call("a", "b", **kwargs)


def test_self_call_is_rejected() -> None:
    with pytest.raises(ValueError, match="itself"):
        Call("a", "a")


def test_unknown_example_lists_available_ones() -> None:
    with pytest.raises(ValueError, match="shop"):
        example("bank")
