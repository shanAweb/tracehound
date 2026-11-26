"""Stage 2 - Detect: flag anomalous signals and estimate when each anomaly began.

``detect(incident)`` compares every metric series with its own baseline (by default the first
third of the recording) and reports, per signal and bad direction, the strongest stretch of
time in which it moved away from normal. That stretch must pass two tests: the statistical
evidence must reach the threshold, and the change must be large enough to matter.
"""

from tracehound.detect.anomaly import Anomaly, DetectConfig, Detection
from tracehound.detect.detector import detect, detect_series
from tracehound.detect.signals import BAD_DIRECTION, MIN_EFFECT, Direction, MinEffect

__all__ = [
    "BAD_DIRECTION",
    "MIN_EFFECT",
    "Anomaly",
    "DetectConfig",
    "Detection",
    "Direction",
    "MinEffect",
    "detect",
    "detect_series",
]
