"""The shared incident-format helpers."""

import pytest

from tracehound import _format as fmt


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (41.2, "41.2"),
        (41.20004, "41.2"),
        (41.20006, "41.2001"),
        (3.0, "3"),
        (100.0, "100"),
        (0.0, "0"),
        (-0.0, "0"),
        (-0.00001, "0"),
        (-2.5, "-2.5"),
        (0.0012, "0.0012"),
    ],
)
def test_format_value_is_rounded_and_trimmed(value: float, expected: str) -> None:
    assert fmt.format_value(value) == expected


def test_format_value_rejects_zero_decimals() -> None:
    # With 0 decimals, trimming zeros would turn "100" into "1".
    with pytest.raises(ValueError):
        fmt.format_value(100.0, decimals=0)


def test_metric_names_are_in_alphabetical_row_order() -> None:
    names = [
        fmt.ERROR_RATE,
        fmt.LATENCY_P50,
        fmt.LATENCY_P95,
        fmt.LATENCY_P99,
        fmt.THROUGHPUT,
        fmt.UTILIZATION,
    ]
    assert names == sorted(names)
