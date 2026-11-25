"""Fault definitions, fault plans, and their exact effect on a single request."""

import random
from collections.abc import Callable

import pytest

from tracehound.sim import Fault, Topology, example
from tracehound.sim.faults import NO_EFFECT, Effect, FaultPlan
from tracehound.sim.request import RequestSimulator, SpanRecord, ms_to_ns

S = 1_000_000_000
TopologyFactory = Callable[..., Topology]


def shop_plan(*faults: Fault, duration_s: int = 100) -> FaultPlan:
    return FaultPlan(list(faults), example("shop"), start_ns=0, end_ns=duration_s * S)


def simulate(topo: Topology, *faults: Fault, at_ns: int = 0) -> dict[str, SpanRecord]:
    plan = FaultPlan(list(faults), topo, start_ns=0, end_ns=100 * S)
    spans = RequestSimulator(topo, random.Random(0), plan).simulate(at_ns, sampled=True)
    return {s.service: s for s in spans}


def took(span: SpanRecord) -> int:
    return span.end_ns - span.start_ns


# --- Fault definition ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "param", "default"),
    [
        ("latency", "added_ms", 850.0),
        ("error", "error_rate", 0.3),
        ("saturation", "time_to_exhaustion_s", 300.0),
        ("regression", "latency_factor", 1.3),
    ],
)
def test_defaults_and_parameter_names(kind: str, param: str, default: float) -> None:
    fault = Fault(kind, "cart")  # type: ignore[arg-type]
    assert (fault.param_name, fault.value) == (param, default)


@pytest.mark.parametrize(
    ("kind", "strength"),
    [("latency", 0), ("error", 0), ("error", 1.5), ("saturation", -1), ("regression", 1.0)],
)
def test_invalid_strength_is_rejected(kind: str, strength: float) -> None:
    with pytest.raises(ValueError, match="strength"):
        Fault(kind, "cart", strength=strength)  # type: ignore[arg-type]


@pytest.mark.parametrize("kwargs", [{"kind": "melting"}, {"at": -5}, {"duration": 0}])
def test_invalid_kind_or_timing_is_rejected(kwargs: dict[str, object]) -> None:
    args: dict[str, object] = {"kind": "latency", "service": "cart", **kwargs}
    with pytest.raises(ValueError):
        Fault(**args)  # type: ignore[arg-type]


# --- Fault plan ---------------------------------------------------------------------------


def test_plan_rejects_unknown_service_and_late_start() -> None:
    with pytest.raises(ValueError, match="unknown service"):
        shop_plan(Fault("latency", "ghost"))
    with pytest.raises(ValueError, match="after the run ends"):
        shop_plan(Fault("latency", "cart", at="2m"), duration_s=100)


def test_effect_applies_only_inside_its_window() -> None:
    plan = shop_plan(Fault("latency", "cart", at=10, duration=20))
    assert plan.effect("cart", 10 * S - 1) == NO_EFFECT
    assert plan.effect("cart", 10 * S) == Effect(extra_ms=850.0)
    assert plan.effect("cart", 30 * S - 1) == Effect(extra_ms=850.0)
    assert plan.effect("cart", 30 * S) == NO_EFFECT
    assert plan.effect("auth", 15 * S) == NO_EFFECT


def test_effects_of_several_faults_combine() -> None:
    plan = shop_plan(
        Fault("latency", "cart", strength=100),
        Fault("latency", "cart", strength=50),
        Fault("regression", "cart", strength=1.5),
        Fault("error", "cart", strength=0.2),
        Fault("error", "cart", strength=0.4),
    )
    assert plan.effect("cart", 0) == Effect(extra_ms=150.0, latency_factor=1.5, error_rate=0.4)


def test_saturation_queues_while_filling_then_rejects() -> None:
    plan = shop_plan(Fault("saturation", "cart", at=10, strength=40))  # full after 40 s
    assert plan.leaked_share("cart", 10 * S) == 0.0
    assert plan.leaked_share("cart", 30 * S) == pytest.approx(0.5)
    assert plan.effect("cart", 30 * S).latency_factor == pytest.approx(2.0)  # 1 / (1 - 0.5)
    assert plan.effect("cart", 49 * S).latency_factor == pytest.approx(20.0)  # capped
    assert plan.effect("cart", 50 * S) == Effect(exhausted=True)
    assert plan.leaked_share("cart", 60 * S) == 1.0


def test_ground_truth_is_sorted_by_onset_and_runs_to_the_end_by_default() -> None:
    plan = shop_plan(
        Fault("error", "payments-db", at=20), Fault("latency", "cart", at=5, duration=10)
    )
    assert plan.ground_truth() == [
        {
            "kind": "latency",
            "service": "cart",
            "start_ns": 5 * S,
            "end_ns": 15 * S,
            "params": {"added_ms": 850.0},
        },
        {
            "kind": "error",
            "service": "payments-db",
            "start_ns": 20 * S,
            "end_ns": 100 * S,
            "params": {"error_rate": 0.3},
        },
    ]


# --- Effect on one request (zero jitter, so times are exact) --------------------------------


def test_latency_fault_adds_time_and_can_trip_the_callers_timeout(chain: TopologyFactory) -> None:
    topo = chain(a_ms=10, b_ms=20, timeout_ms=500)
    small = simulate(topo, Fault("latency", "b", strength=100))
    assert took(small["b"]) == ms_to_ns(120) and not small["a"].error
    big = simulate(topo, Fault("latency", "b"))  # 20 + 850 ms > 500 ms timeout
    assert big["a"].error and not big["b"].error
    assert took(big["a"]) == ms_to_ns(10 + 500)


def test_error_fault_fails_the_service_and_its_caller(chain: TopologyFactory) -> None:
    spans = simulate(chain(), Fault("error", "b", strength=1.0))
    assert spans["b"].error and spans["a"].error


def test_regression_multiplies_own_time(chain: TopologyFactory) -> None:
    spans = simulate(chain(b_ms=20), Fault("regression", "b", strength=1.5))
    assert took(spans["b"]) == ms_to_ns(30)


def test_exhausted_pool_rejects_at_normal_speed(chain: TopologyFactory) -> None:
    spans = simulate(chain(b_ms=20), Fault("saturation", "b", strength=1), at_ns=2 * S)
    assert spans["b"].error and spans["a"].error
    assert took(spans["b"]) == ms_to_ns(20)


def test_fault_has_no_effect_before_its_onset(chain: TopologyFactory) -> None:
    spans = simulate(chain(), Fault("error", "b", at=50, strength=1.0), at_ns=10 * S)
    assert not spans["a"].error and not spans["b"].error
