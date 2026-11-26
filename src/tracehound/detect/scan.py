"""Find the strongest shifted segment of a standardized series (a scan statistic).

Given ``z`` (each point's distance from the baseline level, in noise units), the anomaly is the
contiguous segment ``z[start:end]`` with the largest evidence

    E = sum(z[start:end]) / sqrt(L + L**2 * pi / (2 * n_base)),    L = end - start

This is a two-sample z statistic: the segment's mean against the baseline median. The second
term under the root is the noise of that median, estimated from ``n_base`` points. Without it,
a long segment would look significant merely because the baseline was slightly off.

Searching every segment would cost O(n**2). Instead, for each candidate shift size ``mu``, the
maximum-likelihood segment is the maximum-sum segment of ``z - mu / 2``, found in O(n) with
a cumulative sum. The best evidence over a grid of sizes from 0.5 to 90 sigma is kept. This
finds both edges of a fault that starts and stops, and ignores noise before or after it.
"""

import math
from typing import NamedTuple

import numpy as np
import numpy.typing as npt

SHIFT_SIZES = 2.0 ** np.arange(-1.0, 7.0, 0.5)  # 0.5, 0.71, 1, ..., 90.5 sigma


class Segment(NamedTuple):
    evidence: float
    start: int  # first index in the segment
    end: int  # one past the last index


def evidence(z_sum: float, length: int, n_base: int) -> float:
    """Evidence that a segment of ``length`` points summing to ``z_sum`` is shifted."""
    return z_sum / math.sqrt(length + length * length * math.pi / (2 * n_base))


def max_sum_segment(x: npt.NDArray[np.float64]) -> tuple[int, int]:
    """``(start, end)`` of the contiguous segment with the largest sum, in O(n).

    >>> max_sum_segment(np.array([-1.0, 2.0, 3.0, -9.0, 4.0]))
    (1, 3)
    """
    cumulative = np.concatenate(([0.0], np.cumsum(x)))
    lowest_before = np.minimum.accumulate(cumulative[:-1])
    end = int(np.argmax(cumulative[1:] - lowest_before)) + 1
    return int(np.argmin(cumulative[:end])), end


def strongest_segment(z: npt.NDArray[np.float64], n_base: int) -> Segment:
    """The segment of ``z`` with the highest evidence of an upward shift.

    >>> z = np.array([0.0, 0.0, 0.0, 5.0, 5.0, 5.0, 0.0, 0.0])
    >>> strongest_segment(z, n_base=100)[1:]
    (3, 6)
    """
    if len(z) == 0 or n_base < 1:
        raise ValueError("need at least one point and one baseline point")
    best = Segment(-math.inf, 0, 0)
    for size in SHIFT_SIZES:
        start, end = max_sum_segment(z - size / 2)
        candidate = evidence(float(np.sum(z[start:end])), end - start, n_base)
        if candidate > best.evidence:
            best = Segment(candidate, start, end)
    return best
