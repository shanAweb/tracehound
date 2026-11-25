"""``ground_truth.json``: the faults planted in a simulated run (optional file)."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tracehound.ingest._checks import (
    Where,
    as_int,
    as_number,
    field,
    int_field,
    read_json_object,
    show,
    str_field,
)


@dataclass(frozen=True)
class PlantedFault:
    """One planted fault: what it was, where, and when it was active ``[start_ns, end_ns)``."""

    kind: str
    service: str
    start_ns: int
    end_ns: int
    params: Mapping[str, float]


@dataclass(frozen=True)
class GroundTruth:
    """The true causes of a simulated incident. ``faults`` is sorted by onset."""

    seed: int | None
    faults: tuple[PlantedFault, ...]

    @property
    def services(self) -> tuple[str, ...]:
        """The services that had a fault planted in them, sorted."""
        return tuple(sorted({f.service for f in self.faults}))


def read_ground_truth(path: Path) -> GroundTruth:
    obj = read_json_object(path)
    where = Where(path)
    seed = None if obj.get("seed") is None else as_int(obj["seed"], "seed", where)
    records = field(obj, "faults", where)
    if not isinstance(records, list):
        where.fail(f"faults must be a list, got {show(records)}")
    faults = [_parse_fault(record, i, where) for i, record in enumerate(records)]
    faults.sort(key=lambda f: (f.start_ns, f.service, f.kind))
    return GroundTruth(seed, tuple(faults))


def _parse_fault(record: object, index: int, file: Where) -> PlantedFault:
    if not isinstance(record, dict):
        file.fail(f"faults[{index}] must be a JSON object, got {show(record)}")
    where = Where(file.path, context=f"faults[{index}]")
    start_ns = int_field(record, "start_ns", where)
    end_ns = int_field(record, "end_ns", where)
    if end_ns <= start_ns:
        where.fail(f"end_ns ({end_ns}) must be after start_ns ({start_ns})")
    params = field(record, "params", where)
    if not isinstance(params, dict):
        where.fail(f"params must be a JSON object, got {show(params)}")
    return PlantedFault(
        kind=str_field(record, "kind", where),
        service=str_field(record, "service", where),
        start_ns=start_ns,
        end_ns=end_ns,
        params={str(k): as_number(v, f"params.{k}", where) for k, v in sorted(params.items())},
    )
