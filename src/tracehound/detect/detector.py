"""Detect anomalies in one series (``detect_series``) or in a whole incident (``detect``)."""

import numpy as np
import numpy.typing as npt

from tracehound._format import NS_PER_MS, NS_PER_S
from tracehound.detect import baseline
from tracehound.detect.anomaly import Anomaly, DetectConfig, Detection
from tracehound.detect.scan import strongest_segment
from tracehound.detect.signals import bad_directions, is_material
from tracehound.ingest import Incident

DEFAULT_CONFIG = DetectConfig()


def detect_series(
    service: str,
    signal: str,
    timestamps_ns: npt.NDArray[np.int64],
    values: npt.NDArray[np.float64],
    *,
    baseline_end_ns: int,
    resolution_ns: int,
    config: DetectConfig = DEFAULT_CONFIG,
) -> list[Anomaly] | None:
    """Anomalies in one time-ordered series: at most one per bad direction.

    Points before ``baseline_end_ns`` define normal. The whole series, baseline included, is
    then scanned for its strongest shifted segment. Returns ``None`` when the baseline has
    too few points to judge.
    """
    in_baseline = timestamps_ns < baseline_end_ns
    n_base = int(np.count_nonzero(in_baseline))
    if n_base < config.min_baseline_points:
        return None
    normal = baseline.estimate(values[in_baseline])
    found = []
    for direction in bad_directions(signal):
        sign = 1.0 if direction == "up" else -1.0
        z = sign * (values - normal.level) / normal.scale
        segment = strongest_segment(np.clip(z, -config.clip, config.clip), n_base)
        if segment.evidence < config.threshold:
            continue
        start, end = segment.start, segment.end
        inside = slice(start, end)
        observed = float(np.median(values[inside]))
        if not is_material(signal, normal.level, observed, direction):
            continue
        found.append(
            Anomaly(
                service=service,
                signal=signal,
                direction=direction,
                onset_ns=int(timestamps_ns[start]),
                end_ns=int(timestamps_ns[end - 1]) + resolution_ns,
                resolution_ns=resolution_ns,
                baseline=normal.level,
                observed=observed,
                shift=float(np.median(z[inside])),
                evidence=segment.evidence,
            )
        )
    return found


def detect(incident: Incident, config: DetectConfig = DEFAULT_CONFIG) -> Detection:
    """Check every metric series of ``incident`` against its own baseline window."""
    meta = incident.meta
    window_ns = meta.end_ns - meta.start_ns
    baseline_end_ns = meta.start_ns + round(config.baseline_fraction * window_ns)
    resolution_ns = round(meta.metric_interval_s * NS_PER_S)
    anomalies: list[Anomaly] = []
    skipped: list[tuple[str, str]] = []
    for (service, signal), series in incident.metrics.items():
        found = detect_series(
            service,
            signal,
            series.timestamps_ms * NS_PER_MS,
            series.values,
            baseline_end_ns=baseline_end_ns,
            resolution_ns=resolution_ns,
            config=config,
        )
        if found is None:
            skipped.append((service, signal))
        else:
            anomalies.extend(found)
    anomalies.sort(key=lambda a: (a.onset_ns, a.service, a.signal, a.direction))
    return Detection(
        anomalies=tuple(anomalies),
        baseline_end_ns=baseline_end_ns,
        signals_checked=len(incident.metrics) - len(skipped),
        skipped=tuple(skipped),
        config=config,
    )
