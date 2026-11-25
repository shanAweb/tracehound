"""Stage 1 - Ingest: parse an incident folder (metrics + traces) into typed objects.

``load(folder)`` validates every file and returns an ``Incident``:

- ``meta``: the recording window (``Meta``)
- ``metrics``: one ``Series`` per (service, metric), as numpy arrays (``Metrics``)
- ``spans``: every span as numpy columns, sorted by start time (``Spans``)
- ``ground_truth``: the planted faults, for simulated runs only (``GroundTruth``)
"""

from tracehound.ingest._checks import IncidentFormatError
from tracehound.ingest.ground_truth import GroundTruth, PlantedFault
from tracehound.ingest.incident import Incident, load
from tracehound.ingest.meta import Meta
from tracehound.ingest.metrics import Metrics, Series
from tracehound.ingest.spans import ROOT, Spans

__all__ = [
    "ROOT",
    "GroundTruth",
    "Incident",
    "IncidentFormatError",
    "Meta",
    "Metrics",
    "PlantedFault",
    "Series",
    "Spans",
    "load",
]
