"""Ready-made topologies. ``shop`` is the default demo system.

shop call graph (caller -> callee; the percentage is the share of requests making the call)::

    frontend -> auth
    frontend -> catalog  -> catalog-db
    frontend -> checkout (30%) -> cart     -> payments-db
                               -> payments -> payments-db

``payments-db`` has two callers, so a fault there produces victims on two paths.
"""

from collections.abc import Callable

from tracehound.sim.topology import Call, Service, Topology


def shop() -> Topology:
    """An 8-service web shop. Healthy latencies sit far below every timeout.

    Capacities are sized so that healthy utilization is roughly 0.2-0.35 at 50 rps.
    """
    services = [
        Service("frontend", "GET /", base_ms=8, capacity=10),
        Service("auth", "POST /verify", base_ms=4, capacity=1),
        Service("catalog", "GET /products", base_ms=12, capacity=3),
        Service("catalog-db", "SELECT products", base_ms=6, capacity=1),
        Service("checkout", "POST /checkout", base_ms=15, capacity=6),
        Service("cart", "GET /cart", base_ms=6, capacity=2),
        Service("payments", "POST /charge", base_ms=20, capacity=3),
        Service("payments-db", "UPDATE ledger", base_ms=40, capacity=4),
    ]
    calls = [
        Call("frontend", "auth", timeout_ms=200),
        Call("frontend", "catalog", timeout_ms=500),
        Call("frontend", "checkout", probability=0.3, timeout_ms=2000),
        Call("catalog", "catalog-db", timeout_ms=300),
        Call("checkout", "cart", timeout_ms=800),
        Call("checkout", "payments", timeout_ms=1500),
        Call("cart", "payments-db", timeout_ms=500),
        Call("payments", "payments-db", timeout_ms=500),
    ]
    return Topology("shop", services, calls, entry="frontend")


EXAMPLES: dict[str, Callable[[], Topology]] = {"shop": shop}


def example(name: str) -> Topology:
    """Build a named example topology."""
    if name not in EXAMPLES:
        raise ValueError(f"unknown example {name!r}; available: {sorted(EXAMPLES)}")
    return EXAMPLES[name]()
