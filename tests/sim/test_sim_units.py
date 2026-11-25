"""Duration parsing."""

import pytest

from tracehound.sim.units import parse_duration, seconds_to_ns


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("500ms", 0.5), ("30s", 30.0), ("10m", 600.0), ("1.5h", 5400.0), (" 2m ", 120.0)],
)
def test_parses_unit_strings(text: str, seconds: float) -> None:
    assert parse_duration(text) == seconds


def test_numbers_are_seconds() -> None:
    assert parse_duration(90) == 90.0
    assert parse_duration(0.25) == 0.25


@pytest.mark.parametrize("bad", ["10", "10x", "-5s", "", "m", "1e3s"])
def test_rejects_malformed_strings(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(bad)


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan")])
def test_rejects_non_positive_or_non_finite_numbers(bad: float) -> None:
    with pytest.raises(ValueError):
        parse_duration(bad)


def test_rejects_bool() -> None:
    with pytest.raises(TypeError):
        parse_duration(True)


def test_seconds_to_ns() -> None:
    assert seconds_to_ns(1.5) == 1_500_000_000
    assert seconds_to_ns(600) == 600_000_000_000
