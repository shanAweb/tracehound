"""The scan statistic: exact edges on clean data, and its false-alarm rate on pure noise."""

import math

import numpy as np
import pytest

from tracehound.detect import baseline
from tracehound.detect.scan import evidence, strongest_segment


def test_evidence_accounts_for_the_noise_of_the_baseline() -> None:
    assert evidence(10.0, 4, n_base=10**9) == pytest.approx(10.0 / 2.0)  # plain sum / sqrt(L)
    long_segment = evidence(2.0 * 400, 400, n_base=100)  # mean 2 sigma over 400 points
    assert long_segment == pytest.approx(800 / math.sqrt(400 + 400**2 * math.pi / 200))
    assert long_segment < 2.0 * math.sqrt(2 * 100 / math.pi) + 1e-9  # capped by the baseline


@pytest.mark.parametrize("size", [0.8, 3.0, 40.0])
def test_a_step_is_found_at_its_exact_edges(size: float) -> None:
    z = np.concatenate([np.zeros(200), np.full(150, size)])
    _, start, end = strongest_segment(z, n_base=100)
    assert (start, end) == (200, 350)


def test_a_fault_that_ends_is_found_with_both_edges() -> None:
    z = np.concatenate([np.zeros(100), np.full(30, 6.0), np.zeros(100)])
    assert strongest_segment(z, n_base=100)[1:] == (100, 130)


def test_the_strongest_of_two_bursts_wins() -> None:
    z = np.zeros(300)
    z[50:53] = 3.0  # short, weak
    z[200:260] = 5.0  # long, strong
    assert strongest_segment(z, n_base=100)[1:] == (200, 260)


def test_no_shift_gives_no_evidence() -> None:
    assert strongest_segment(np.full(50, -1.0), n_base=20).evidence < 0


def test_empty_input_is_rejected() -> None:
    with pytest.raises(ValueError):
        strongest_segment(np.array([]), n_base=10)


@pytest.mark.parametrize(("n", "trials"), [(40, 1500), (600, 800)])
def test_false_alarm_rate_on_gaussian_noise_is_below_0_3_percent(n: int, trials: int) -> None:
    # The default threshold (7) and clip (4), with the first third as baseline, as in detect().
    rng = np.random.default_rng(n)
    alarms = 0
    for _ in range(trials):
        x = rng.standard_normal(n)
        normal = baseline.estimate(x[: n // 3])
        z = np.clip((x - normal.level) / normal.scale, -4.0, 4.0)
        alarms += strongest_segment(z, n_base=n // 3).evidence >= 7.0
    assert alarms / trials <= 0.003
