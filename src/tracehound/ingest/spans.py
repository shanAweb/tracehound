"""``traces.jsonl``: every recorded span, held as columns (one numpy array per field)."""

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tracehound._format import STATUS_ERROR, STATUS_OK
from tracehound.ingest._checks import (
    Where,
    as_str,
    field,
    int_field,
    open_text,
    parse_json,
    show,
    str_field,
)
from tracehound.ingest.meta import Meta

ROOT = ""  # parent_span_id of a root span


@dataclass(frozen=True, eq=False, repr=False)
class Spans:
    """All spans of an incident as equal-length, read-only columns.

    Row ``i`` is one span. Rows are sorted by ``(start_ns, span_id)``, whatever the order in
    the file. A root span has ``parent_span_id == ROOT`` (the empty string).
    """

    trace_id: npt.NDArray[np.str_]
    span_id: npt.NDArray[np.str_]
    parent_span_id: npt.NDArray[np.str_]
    service: npt.NDArray[np.str_]
    name: npt.NDArray[np.str_]
    start_ns: npt.NDArray[np.int64]
    end_ns: npt.NDArray[np.int64]
    error: npt.NDArray[np.bool_]

    def __post_init__(self) -> None:
        columns = [getattr(self, f.name) for f in fields(self)]
        if len({len(c) for c in columns}) > 1:
            raise ValueError("every span column must have the same length")
        for column in columns:
            column.setflags(write=False)

    def __len__(self) -> int:
        return len(self.start_ns)

    def __repr__(self) -> str:
        return f"Spans(n={len(self)}, services={len(self.services)})"

    @property
    def duration_ns(self) -> npt.NDArray[np.int64]:
        return self.end_ns - self.start_ns

    @property
    def services(self) -> tuple[str, ...]:
        return tuple(str(s) for s in np.unique(self.service))

    def select(self, mask: npt.NDArray[np.bool_]) -> "Spans":
        """The spans where ``mask`` is true, in the same order."""
        return Spans(*(getattr(self, f.name)[mask] for f in fields(self)))

    def of_service(self, service: str) -> "Spans":
        return self.select(self.service == service)


_Row = tuple[str, str, str, str, str, int, int, bool]


def read_spans(path: Path, meta: Meta) -> Spans:
    """Read ``traces.jsonl``: one JSON object per line. Blank lines are skipped."""
    rows: list[_Row] = []
    first_seen: dict[tuple[str, str], int] = {}
    with open_text(path) as f:
        for line, text in enumerate(f, start=1):
            if not text.strip():
                continue
            where = Where(path, line)
            row = _parse_span(parse_json(text, where), meta, where)
            key = (row[0], row[1])  # (trace_id, span_id)
            if key in first_seen:
                first = first_seen[key]
                where.fail(f"duplicate span_id {row[1]!r} in its trace (first on line {first})")
            first_seen[key] = line
            rows.append(row)
    return _to_columns(rows)


def _parse_span(obj: object, meta: Meta, where: Where) -> _Row:
    if not isinstance(obj, dict):
        where.fail(f"expected a JSON object, got {show(obj)}")
    parent = obj.get("parent_span_id")  # missing, null or "" all mean "root"
    parent = ROOT if parent in (None, ROOT) else as_str(parent, "parent_span_id", where)
    start_ns = int_field(obj, "start_ns", where)
    end_ns = int_field(obj, "end_ns", where)
    if not meta.contains(start_ns):
        where.fail(f"start_ns {start_ns} is outside the recording window in meta.json")
    if end_ns < start_ns:
        where.fail(f"end_ns ({end_ns}) is before start_ns ({start_ns})")
    status = field(obj, "status", where)
    if status not in (STATUS_OK, STATUS_ERROR):
        where.fail(f"status must be {STATUS_OK!r} or {STATUS_ERROR!r}, got {show(status)}")
    return (
        str_field(obj, "trace_id", where),
        str_field(obj, "span_id", where),
        parent,
        str_field(obj, "service", where),
        str_field(obj, "name", where),
        start_ns,
        end_ns,
        status == STATUS_ERROR,
    )


def _to_columns(rows: list[_Row]) -> Spans:
    dtypes = (np.str_,) * 5 + (np.int64, np.int64, np.bool_)
    columns: list[npt.NDArray[Any]] = [
        np.array([r[i] for r in rows], dtype=t) for i, t in enumerate(dtypes)
    ]
    order = np.lexsort((columns[1], columns[5]))  # by start_ns, then span_id
    return Spans(*(c[order] for c in columns))
