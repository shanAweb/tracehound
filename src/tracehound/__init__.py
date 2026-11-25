"""Tracehound: an offline, dependency-graph root-cause engine for distributed systems.

Reads recorded metrics and traces, finds what is drifting, and ranks the most likely
root cause with evidence. Pure Python, no model download, no API key.

The public API grows stage by stage (see the roadmap in README.md). Available now:
``load(folder)`` reads and validates an incident folder into an ``Incident``.
"""

from tracehound.ingest import Incident, IncidentFormatError, load

__version__ = "0.1.0.dev0"

__all__ = ["Incident", "IncidentFormatError", "__version__", "load"]
