"""``Incident`` and ``load()``: one validated incident folder, ready for analysis."""

from dataclasses import dataclass
from pathlib import Path

from tracehound import _format as fmt
from tracehound.ingest._checks import IncidentFormatError
from tracehound.ingest.ground_truth import GroundTruth, read_ground_truth
from tracehound.ingest.meta import Meta, read_meta
from tracehound.ingest.metrics import Metrics, read_metrics
from tracehound.ingest.spans import Spans, read_spans

REQUIRED_FILES = (fmt.META_FILE, fmt.METRICS_FILE, fmt.TRACES_FILE)


@dataclass(frozen=True, eq=False, repr=False)
class Incident:
    """Everything recorded about one incident, or one load-test run.

    ``ground_truth`` is only present for simulated runs (``ground_truth.json``).
    """

    meta: Meta
    metrics: Metrics
    spans: Spans
    ground_truth: GroundTruth | None = None
    path: Path | None = None

    @property
    def services(self) -> tuple[str, ...]:
        """Every service seen in the metrics or the traces, sorted."""
        return tuple(sorted(set(self.metrics.services) | set(self.spans.services)))

    def __repr__(self) -> str:
        faults = "none" if self.ground_truth is None else len(self.ground_truth.faults)
        return (
            f"Incident(path={str(self.path)!r}, services={len(self.services)}, "
            f"duration_s={self.meta.duration_s:g}, series={len(self.metrics)}, "
            f"spans={len(self.spans)}, planted_faults={faults})"
        )


def load(folder: str | Path) -> Incident:
    """Read and validate an incident folder (format: see "Input format" in the README).

    Raises ``FileNotFoundError`` if ``folder`` is not a directory, and ``IncidentFormatError``,
    naming the file and line, for the first problem found inside it. Rows and spans may be in
    any order: the result is sorted, so the same data always loads the same way.
    """
    path = Path(folder)
    if not path.is_dir():
        raise FileNotFoundError(f"incident folder not found: {path}")
    for name in REQUIRED_FILES:
        if not (path / name).is_file():
            raise IncidentFormatError(path / name, "required file is missing")
    meta = read_meta(path / fmt.META_FILE)
    truth_file = path / fmt.GROUND_TRUTH_FILE
    return Incident(
        meta=meta,
        metrics=read_metrics(path / fmt.METRICS_FILE, meta),
        spans=read_spans(path / fmt.TRACES_FILE, meta),
        ground_truth=read_ground_truth(truth_file) if truth_file.is_file() else None,
        path=path,
    )
