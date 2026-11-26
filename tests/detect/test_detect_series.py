"""``detect_series`` on synthetic signals whose answer is known exactly."""

import numpy as np
import pytest

from tracehound.detect import Anomaly, DetectConfig, detect_series
from tracehound.detect.baseline import estimate

S = 1_000_000_000
N = 300  # one point per second; the first 100 are the baseline


def series(values: np.ndarray, signal: str = "latency_p50_ms") -> list[Anomaly] | None:
    timestamps = np.arange(len(values), dtype=np.int64) * S
    return detect_series(
        "svc", signal, timestamps, values.astype(np.float64), baseline_end_ns=100 * S,
        resolution_ns=S,
    )  # fmt: skip


def noise(level: float, sd: float, seed: int = 0, n: int = N) -> np.ndarray:
    return level + sd * np.random.default_rng(seed).standard_normal(n)


def test_a_latency_step_is_reported_with_exact_onset_and_levels() -> None:
    x = noise(40.0, 2.0)
    x[180:] += 860.0
    (a,) = series(x) or []
    assert (a.service, a.signal, a.direction) == ("svc", "latency_p50_ms", "up")
    assert (a.onset_ns, a.end_ns, a.resolution_ns) == (180 * S, N * S, S)
    assert a.baseline == pytest.approx(40.0, abs=0.5)
    assert a.observed == pytest.approx(900.0, abs=1.0)
    assert a.shift > 100 and a.evidence >= 7


def test_a_partly_affected_first_interval_is_kept() -> None:
    x = noise(40.0, 2.0)
    normal = estimate(x[:100])
    x[180] = normal.level + 30 * normal.scale  # the fault began partway through this interval
    x[181:] += 860.0
    (a,) = series(x) or []
    assert a.onset_ns == 180 * S


def test_a_fault_that_ends_is_reported_with_its_end() -> None:
    x = noise(40.0, 2.0)
    x[150:210] *= 3
    (a,) = series(x) or []
    assert (a.onset_ns, a.end_ns) == (150 * S, 210 * S)


def test_a_change_inside_the_baseline_window_is_still_found() -> None:
    x = noise(40.0, 2.0)
    x[70:] += 100.0  # starts before the baseline window ends; the median resists it
    (a,) = series(x) or []
    assert a.onset_ns == 70 * S


def test_throughput_is_only_bad_when_it_drops() -> None:
    drop, rise = noise(50.0, 3.0), noise(50.0, 3.0)
    drop[200:] *= 0.5
    rise[200:] *= 1.5
    assert [a.direction for a in series(drop, "throughput_rps") or []] == ["down"]
    assert series(rise, "throughput_rps") == []


def test_an_unknown_metric_is_checked_in_both_directions() -> None:
    x = noise(10.0, 0.5)
    x[120:160] += 5.0
    x[220:260] -= 5.0
    assert [a.direction for a in series(x, "queue_depth") or []] == ["up", "down"]


def test_noise_spikes_and_tiny_shifts_are_not_reported() -> None:
    assert series(noise(40.0, 2.0)) == []
    spiky = noise(40.0, 2.0)
    spiky[[130, 190, 250]] = 5000.0  # each point counts for at most `clip` sigma
    assert series(spiky) == []
    tiny = noise(40.0, 0.5)
    tiny[150:] += 2.0  # +5%: overwhelming evidence, but below the 10% minimum effect
    assert series(tiny) == []


def test_an_error_rate_from_zero_is_detected() -> None:
    x = np.zeros(N)
    x[[20, 60, 95]] = 0.02  # a few healthy errors
    x[200:] = 0.3
    (a,) = series(x, "error_rate") or []
    assert a.onset_ns == 200 * S and a.observed == pytest.approx(0.3)


def test_too_short_a_baseline_is_skipped_not_guessed() -> None:
    x = noise(40.0, 2.0, n=20)
    timestamps = np.arange(20, dtype=np.int64) * S
    result = detect_series("svc", "latency_p50_ms", timestamps, x, baseline_end_ns=5 * S,
                           resolution_ns=S)  # fmt: skip
    assert result is None


def test_config_is_validated() -> None:
    with pytest.raises(ValueError):
        DetectConfig(baseline_fraction=1.0)
    with pytest.raises(ValueError):
        DetectConfig(threshold=0)
