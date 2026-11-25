"""``meta.json``: the recording window and how the telemetry was collected."""

from dataclasses import dataclass
from pathlib import Path

from tracehound._format import FORMAT_VERSION, NS_PER_S
from tracehound.ingest._checks import (
    Where,
    as_number,
    as_str,
    int_field,
    number_field,
    read_json_object,
)


@dataclass(frozen=True)
class Meta:
    """What ``meta.json`` says about the recording.

    ``trace_sample_rate`` and ``source`` are optional and ``None`` when unknown.
    """

    format_version: int
    start_ns: int
    end_ns: int
    metric_interval_s: float
    trace_sample_rate: float | None = None
    source: str | None = None

    @property
    def duration_s(self) -> float:
        return (self.end_ns - self.start_ns) / NS_PER_S

    def contains(self, t_ns: int) -> bool:
        """Whether ``t_ns`` is inside the recording window ``[start_ns, end_ns)``."""
        return self.start_ns <= t_ns < self.end_ns


def read_meta(path: Path) -> Meta:
    obj = read_json_object(path)
    where = Where(path)
    version = int_field(obj, "format_version", where)
    if version != FORMAT_VERSION:
        hint = "upgrade tracehound to read it" if version > FORMAT_VERSION else "it is invalid"
        where.fail(f"format_version {version} is not supported ({hint}); expected {FORMAT_VERSION}")
    start_ns = int_field(obj, "start_ns", where)
    end_ns = int_field(obj, "end_ns", where)
    if end_ns <= start_ns:
        where.fail(f"end_ns ({end_ns}) must be after start_ns ({start_ns})")
    interval_s = number_field(obj, "metric_interval_s", where)
    if interval_s <= 0:
        where.fail(f"metric_interval_s must be > 0, got {interval_s}")

    rate: float | None = None
    if obj.get("trace_sample_rate") is not None:
        rate = as_number(obj["trace_sample_rate"], "trace_sample_rate", where)
        if not 0 < rate <= 1:
            where.fail(f"trace_sample_rate must be in (0, 1], got {rate}")
    source = None if obj.get("source") is None else as_str(obj["source"], "source", where)
    return Meta(version, start_ns, end_ns, interval_s, rate, source)
