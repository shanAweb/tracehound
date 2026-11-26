"""Detection results: ``Anomaly``, ``Detection`` and the ``DetectConfig`` that produced them."""

from dataclasses import dataclass

from tracehound.detect.signals import Direction


@dataclass(frozen=True)
class DetectConfig:
    """Detector settings. The defaults are justified in the README ("How Detect works").

    - ``baseline_fraction``: the first part of the recording, assumed mostly normal.
    - ``threshold``: minimum evidence. 7 keeps the false-alarm chance per signal below 0.1% on
      Gaussian noise, for any series length from 40 to 3,600 points.
    - ``clip``: each point counts for at most this many noise units, so a single wild sample
      cannot create an anomaly on its own.
    - ``min_baseline_points``: fewer than this and the signal is skipped, not guessed at.
    """

    baseline_fraction: float = 1 / 3
    threshold: float = 7.0
    clip: float = 4.0
    min_baseline_points: int = 10

    def __post_init__(self) -> None:
        if not 0 < self.baseline_fraction < 1:
            raise ValueError("baseline_fraction must be between 0 and 1")
        if self.threshold <= 0 or self.clip <= 0 or self.min_baseline_points < 2:
            raise ValueError("threshold and clip must be > 0, min_baseline_points >= 2")


@dataclass(frozen=True)
class Anomaly:
    """A signal of one service that moved in its bad direction for a stretch of time.

    The change began somewhere in ``[onset_ns, onset_ns + resolution_ns)``, where
    ``resolution_ns`` is the signal's sampling interval. ``shift`` is the median distance from
    normal during the anomaly, in noise units (sigma). ``evidence`` is the scan statistic that
    passed the threshold.
    """

    service: str
    signal: str
    direction: Direction
    onset_ns: int
    end_ns: int
    resolution_ns: int
    baseline: float
    observed: float
    shift: float
    evidence: float

    @property
    def duration_s(self) -> float:
        return (self.end_ns - self.onset_ns) / 1e9


@dataclass(frozen=True)
class Detection:
    """Every anomaly in an incident, sorted by onset, then service, signal and direction.

    ``skipped`` lists ``(service, signal)`` pairs with too few baseline points to judge.
    """

    anomalies: tuple[Anomaly, ...]
    baseline_end_ns: int
    signals_checked: int
    skipped: tuple[tuple[str, str], ...]
    config: DetectConfig

    @property
    def services(self) -> tuple[str, ...]:
        """Services with at least one anomaly, sorted."""
        return tuple(sorted({a.service for a in self.anomalies}))

    def of_service(self, service: str) -> tuple[Anomaly, ...]:
        return tuple(a for a in self.anomalies if a.service == service)
