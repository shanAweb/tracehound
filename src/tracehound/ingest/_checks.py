"""Validation helpers shared by the readers: one error type and typed field access.

Problems are reported like compiler errors, with the file and, where it makes sense, the
line: ``incident/metrics.csv:17: value must be a number, got 'abc'``.
"""

import json
import math
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, TextIO

_INT64_LIMIT = 2**63
_INTEGER = re.compile(r"-?[0-9]+")


class IncidentFormatError(ValueError):
    """An incident folder does not follow the format. The message says where and why."""

    __module__ = "tracehound"  # shown in tracebacks; ``tracehound.IncidentFormatError`` is public

    def __init__(self, path: Path, problem: str, line: int | None = None) -> None:
        self.path, self.problem, self.line = path, problem, line
        where = str(path) if line is None else f"{path}:{line}"
        super().__init__(f"{where}: {problem}")


@dataclass(frozen=True)
class Where:
    """A position in an incident file, used to report a problem there."""

    path: Path
    line: int | None = None
    context: str = ""  # names the part of the file, e.g. "faults[2]"

    def fail(self, problem: str) -> NoReturn:
        text = f"{self.context}: {problem}" if self.context else problem
        raise IncidentFormatError(self.path, text, self.line)


def show(value: object) -> str:
    """A short ``repr`` for error messages."""
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


def as_int(value: object, what: str, where: Where) -> int:
    if isinstance(value, bool) or not isinstance(value, int):  # bool is an int in Python
        where.fail(f"{what} must be an integer, got {show(value)}")
    if not -_INT64_LIMIT <= value < _INT64_LIMIT:
        where.fail(f"{what} does not fit in a 64-bit integer")
    return value


def as_number(value: object, what: str, where: Where) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        where.fail(f"{what} must be a number, got {show(value)}")
    if not math.isfinite(value):
        where.fail(f"{what} must be finite, got {show(value)}")
    return float(value)


def as_str(value: object, what: str, where: Where) -> str:
    if not isinstance(value, str) or not value:
        where.fail(f"{what} must be a non-empty string, got {show(value)}")
    return value


def field(obj: Mapping[str, object], key: str, where: Where) -> object:
    if key not in obj:
        where.fail(f"missing required field {key!r}")
    return obj[key]


def int_field(obj: Mapping[str, object], key: str, where: Where) -> int:
    return as_int(field(obj, key, where), key, where)


def number_field(obj: Mapping[str, object], key: str, where: Where) -> float:
    return as_number(field(obj, key, where), key, where)


def str_field(obj: Mapping[str, object], key: str, where: Where) -> str:
    return as_str(field(obj, key, where), key, where)


def parse_int_text(text: str, what: str, where: Where) -> int:
    """Parse a plain decimal integer such as ``-12``. ``int()`` alone would accept ``1_000``."""
    if not _INTEGER.fullmatch(text):
        where.fail(f"{what} must be an integer, got {show(text)}")
    return as_int(int(text), what, where)


def parse_number_text(text: str, what: str, where: Where) -> float:
    try:
        value: float | None = float(text)
    except ValueError:
        value = None
    if value is None:  # raised outside ``except`` so the traceback shows only this error
        where.fail(f"{what} must be a number, got {show(text)}")
    return as_number(value, what, where)


class _NonFiniteError(ValueError):
    pass


def _reject_constant(name: str) -> NoReturn:
    raise _NonFiniteError(f"{name} is not allowed: JSON numbers must be finite")


# Built once: json.loads(text, parse_constant=...) would build a new decoder for every line.
_DECODER = json.JSONDecoder(parse_constant=_reject_constant)


def parse_json(text: str, where: Where) -> object:
    """Parse JSON text. ``NaN`` and ``Infinity``, which Python would otherwise accept, fail."""
    try:
        return _DECODER.decode(text)
    except json.JSONDecodeError as e:
        line = where.line if where.line is not None else e.lineno
        raise IncidentFormatError(where.path, f"invalid JSON: {e.msg}", line) from None
    except _NonFiniteError as e:
        raise IncidentFormatError(where.path, str(e), where.line) from None


def read_json_object(path: Path) -> dict[str, object]:
    """Read a whole-file JSON document that must be an object (``meta.json`` and friends)."""
    with open_text(path) as f:
        obj = parse_json(f.read(), Where(path))
    if not isinstance(obj, dict):
        Where(path).fail("expected a JSON object")
    return obj


@contextmanager
def open_text(path: Path) -> Iterator[TextIO]:
    """Open a UTF-8 text file. A decoding error anywhere while reading becomes a format error."""
    try:
        with path.open(encoding="utf-8", newline="") as f:
            yield f
    except UnicodeDecodeError as e:
        raise IncidentFormatError(path, f"not valid UTF-8 text ({e.reason})") from None
