"""Shared fixtures for simulator tests: tiny, fully deterministic topologies."""

from collections.abc import Callable

import pytest

from tracehound.sim import Call, Service, Topology

TopologyFactory = Callable[..., Topology]


@pytest.fixture
def chain() -> TopologyFactory:
    """Build ``a -> b`` (optionally ``a -> c`` after it) with zero jitter, so times are exact.

    Every service takes exactly its ``*_ms`` of own time; errors only happen where asked.
    """

    def build(
        a_ms: float = 10.0,
        b_ms: float = 20.0,
        timeout_ms: float = 1000.0,
        a_error: float = 0.0,
        b_error: float = 0.0,
        with_c: bool = False,
    ) -> Topology:
        services = [
            Service("a", "A", base_ms=a_ms, jitter=0.0, error_rate=a_error),
            Service("b", "B", base_ms=b_ms, jitter=0.0, error_rate=b_error),
        ]
        calls = [Call("a", "b", timeout_ms=timeout_ms)]
        if with_c:
            services.append(Service("c", "C", base_ms=5.0, jitter=0.0, error_rate=0.0))
            calls.append(Call("a", "c"))
        return Topology("chain", services, calls, entry="a")

    return build
