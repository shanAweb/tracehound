"""``metrics.csv``: one time series per (service, metric)."""

import csv
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from tracehound._format import METRICS_HEADER, NS_PER_MS
from tracehound.ingest._checks import Where, open_text, parse_int_text, parse_number_text
from tracehound.ingest.meta import Meta


@dataclass(frozen=True, eq=False, repr=False)
class Series:
    """One metric of one service. ``values[i]`` covers the interval starting at
    ``timestamps_ms[i]``. Timestamps strictly increase; both arrays are read-only."""

    service: str
    metric: str
    timestamps_ms: npt.NDArray[np.int64]
    values: npt.NDArray[np.float64]

    def __post_init__(self) -> None:
        if self.timestamps_ms.shape != self.values.shape or self.values.ndim != 1:
            raise ValueError("timestamps_ms and values must be 1-D arrays of the same length")
        if np.any(np.diff(self.timestamps_ms) <= 0):
            raise ValueError("timestamps_ms must be strictly increasing")
        self.timestamps_ms.setflags(write=False)
        self.values.setflags(write=False)

    def __len__(self) -> int:
        return len(self.values)

    def __repr__(self) -> str:
        return f"Series(service={self.service!r}, metric={self.metric!r}, n={len(self)})"


class Metrics(Mapping[tuple[str, str], Series]):
    """Every series of an incident, keyed by ``(service, metric)`` and iterated in that order."""

    def __init__(self, series: Iterable[Series] = ()) -> None:
        by_key: dict[tuple[str, str], Series] = {}
        for s in series:
            if (s.service, s.metric) in by_key:
                raise ValueError(f"two series for {s.service} {s.metric}")
            by_key[(s.service, s.metric)] = s
        self._series = dict(sorted(by_key.items()))

    def __getitem__(self, key: tuple[str, str]) -> Series:
        return self._series[key]

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(self._series)

    def __len__(self) -> int:
        return len(self._series)

    def __repr__(self) -> str:
        return f"Metrics(series={len(self)}, services={len(self.services)})"

    @property
    def services(self) -> tuple[str, ...]:
        return tuple(sorted({service for service, _ in self._series}))

    def of_service(self, service: str) -> dict[str, Series]:
        """The series of one service, keyed by metric name."""
        return {metric: s for (svc, metric), s in self._series.items() if svc == service}


def read_metrics(path: Path, meta: Meta) -> Metrics:
    """Read ``metrics.csv``. Rows may come in any order; each series is sorted by time."""
    samples: dict[tuple[str, str], dict[int, tuple[float, int]]] = {}
    with open_text(path) as f:
        reader = csv.reader(f)
        header = next(reader, None)
        expected = ",".join(METRICS_HEADER)
        if header is None:
            Where(path, 1).fail(f"the file is empty; expected the header {expected!r}")
        if tuple(header) != METRICS_HEADER:
            Where(path, 1).fail(f"header must be {expected!r}, got {','.join(header)!r}")
        for row in reader:
            if row:  # blank lines are skipped
                where = Where(path, reader.line_num)
                key, timestamp_ms, value = _parse_row(row, meta, where)
                series = samples.setdefault(key, {})
                if timestamp_ms in series:
                    first = series[timestamp_ms][1]
                    where.fail(f"duplicate sample for {key[0]} {key[1]} (first on line {first})")
                series[timestamp_ms] = (value, reader.line_num)
    return Metrics(_to_series(key, rows) for key, rows in samples.items())


def _parse_row(row: list[str], meta: Meta, where: Where) -> tuple[tuple[str, str], int, float]:
    if len(row) != len(METRICS_HEADER):
        where.fail(f"expected {len(METRICS_HEADER)} fields, got {len(row)}")
    ts_text, service, metric, value_text = row
    timestamp_ms = parse_int_text(ts_text, "timestamp_ms", where)
    if not meta.contains(timestamp_ms * NS_PER_MS):
        where.fail(f"timestamp_ms {timestamp_ms} is outside the recording window in meta.json")
    for name, text in (("service", service), ("metric", metric)):
        if not text:
            where.fail(f"{name} must not be empty")
    return (service, metric), timestamp_ms, parse_number_text(value_text, "value", where)


def _to_series(key: tuple[str, str], rows: Mapping[int, tuple[float, int]]) -> Series:
    timestamps = np.fromiter(rows.keys(), dtype=np.int64, count=len(rows))
    values = np.fromiter((v for v, _ in rows.values()), dtype=np.float64, count=len(rows))
    order = np.argsort(timestamps, kind="stable")
    return Series(key[0], key[1], timestamps[order], values[order])
