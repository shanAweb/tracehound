"""A signal's normal level and noise, estimated from its baseline window."""

from typing import NamedTuple

import numpy as np
import numpy.typing as npt

MAD_TO_SIGMA = 1.4826  # MAD x 1.4826 estimates the standard deviation of normal data
RELATIVE_SCALE_FLOOR = 0.01  # noise is never taken as below 1% of the level
ABSOLUTE_SCALE_FLOOR = 1e-9  # ... nor as zero, which would make every change infinite


class Baseline(NamedTuple):
    """Normal ``level`` and noise ``scale`` of a signal, from ``n`` baseline points."""

    level: float
    scale: float
    n: int


def estimate(values: npt.NDArray[np.float64]) -> Baseline:
    """Robust level and scale: median and MAD, so outliers in the baseline do not matter.

    When over half the points share one value, MAD is 0. This is typical of error rates, which
    are mostly exactly 0. Then the mean and standard deviation are used: for rare counts the
    median (0) sits below the true mean and would make pure noise look like a rise.

    >>> estimate(np.array([10.0, 11.0, 9.0, 10.0, 50.0]))
    Baseline(level=10.0, scale=1.4826, n=5)
    """
    median = float(np.median(values))
    scale = MAD_TO_SIGMA * float(np.median(np.abs(values - median)))
    level = median
    if scale == 0:
        level, scale = float(np.mean(values)), float(np.std(values))
    floor = max(RELATIVE_SCALE_FLOOR * abs(level), ABSOLUTE_SCALE_FLOOR)
    return Baseline(level, max(scale, floor), len(values))
