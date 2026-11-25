"""Fault-injection simulator: synthetic microservice telemetry with known root causes.

>>> from tracehound.sim import System
>>> run = System.example("shop").run(duration="5s", rps=20, seed=1)
>>> run.n_requests > 0
True
"""

from tracehound.sim.examples import EXAMPLES, example
from tracehound.sim.faults import Fault
from tracehound.sim.system import SimRun, System
from tracehound.sim.topology import Call, Service, Topology

__all__ = ["EXAMPLES", "Call", "Fault", "Service", "SimRun", "System", "Topology", "example"]
