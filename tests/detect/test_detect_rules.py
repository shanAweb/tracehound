"""Baseline estimation, bad directions and minimum effect sizes."""

import numpy as np
import pytest

from tracehound.detect import BAD_DIRECTION, Direction
from tracehound.detect.baseline import MAD_TO_SIGMA, estimate
from tracehound.detect.signals import bad_directions, is_material


def test_baseline_is_median_and_mad_and_ignores_outliers() -> None:
    values = np.array([10.0, 11.0, 9.0, 10.0, 12.0, 8.0, 10.0, 1000.0])
    level, scale, n = estimate(values)
    assert (level, n) == (10.0, 8)
    assert scale == pytest.approx(MAD_TO_SIGMA * 1.0)


def test_mostly_zero_baseline_uses_mean_and_std() -> None:
    values = np.array([0.0] * 18 + [0.05, 0.1])  # an error rate: mostly exactly 0
    level, scale, _ = estimate(values)
    assert level == pytest.approx(0.0075)
    assert scale == pytest.approx(float(np.std(values)))


def test_scale_is_never_below_one_percent_of_the_level_or_zero() -> None:
    assert estimate(np.full(30, 200.0)).scale == pytest.approx(2.0)
    assert estimate(np.zeros(30)).scale == pytest.approx(1e-9)


def test_every_standard_metric_has_one_bad_direction() -> None:
    assert BAD_DIRECTION["throughput_rps"] == "down"
    assert bad_directions("latency_p99_ms") == ("up",)
    assert bad_directions("queue_depth") == ("up", "down")


@pytest.mark.parametrize(
    ("metric", "baseline", "observed", "direction", "material"),
    [
        ("latency_p50_ms", 40.0, 44.5, "up", True),  # +11%
        ("latency_p50_ms", 40.0, 43.0, "up", False),  # +7.5%: real maybe, but too small
        ("latency_p50_ms", 40.0, 20.0, "up", False),  # faster is not worse
        ("error_rate", 0.002, 0.015, "up", True),  # +1.3 points
        ("error_rate", 0.002, 0.009, "up", False),  # +0.7 points
        ("throughput_rps", 15.0, 11.0, "down", True),  # -27%
        ("throughput_rps", 15.0, 13.0, "down", False),  # -13%
        ("utilization", 0.30, 0.40, "up", True),
        ("utilization", 0.30, 0.33, "up", False),
        ("queue_depth", 10.0, 8.5, "down", True),  # unknown metric: 10% either way
    ],
)
def test_minimum_effect_sizes(
    metric: str, baseline: float, observed: float, direction: Direction, material: bool
) -> None:
    assert is_material(metric, baseline, observed, direction) is material
