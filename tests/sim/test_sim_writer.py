"""Saving a run: file layout, format compliance and byte-level determinism."""

import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tracehound import _format as fmt
from tracehound.sim import SimRun, System
from tracehound.sim.request import SpanRecord
from tracehound.sim.writer import write_incident

FILES = [fmt.META_FILE, fmt.METRICS_FILE, fmt.TRACES_FILE, fmt.GROUND_TRUTH_FILE]


def small_run(seed: int = 5) -> SimRun:
    return System.example("shop").run(duration="20s", rps=20, seed=seed)


def digests(folder: Path) -> dict[str, str]:
    return {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in FILES}


@pytest.fixture(scope="module")
def folder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return small_run().save(tmp_path_factory.mktemp("incident") / "nested" / "run")


def test_all_four_files_are_written(folder: Path) -> None:
    assert sorted(p.name for p in folder.iterdir()) == sorted(FILES)


def test_metrics_csv_format(folder: Path) -> None:
    with (folder / fmt.METRICS_FILE).open(newline="") as f:
        rows = list(csv.reader(f))
    assert tuple(rows[0]) == fmt.METRICS_HEADER
    keys = [(service, metric, int(ts)) for ts, service, metric, _ in rows[1:]]
    assert keys == sorted(keys)
    assert all(float(value) >= 0 for *_, value in rows[1:])


def test_traces_jsonl_format(folder: Path) -> None:
    lines = (folder / fmt.TRACES_FILE).read_text().splitlines()
    records = [json.loads(line) for line in lines]
    assert records, "a 20 s run should sample some traces"
    assert all(tuple(r) == fmt.TRACE_FIELDS for r in records)  # exact keys, fixed order
    assert {r["status"] for r in records} <= {fmt.STATUS_OK, fmt.STATUS_ERROR}
    order = [(r["start_ns"], r["span_id"]) for r in records]
    assert order == sorted(order)


def test_line_endings_are_unix_only(folder: Path) -> None:
    for name in FILES:
        data = (folder / name).read_bytes()
        assert b"\r" not in data and data.endswith(b"\n")


def test_same_seed_is_byte_identical(folder: Path, tmp_path: Path) -> None:
    again = small_run().save(tmp_path / "again")
    assert digests(again) == digests(folder)
    assert digests(small_run(seed=6).save(tmp_path / "other")) != digests(folder)


def test_byte_identical_across_processes_with_different_hash_seeds(tmp_path: Path) -> None:
    # String hashing (and so set/dict-of-set order) is randomized per process.
    script = (
        "import sys; from tracehound.sim import System; "
        "System.example('shop').run(duration='20s', rps=20, seed=5).save(sys.argv[1])"
    )
    outputs = []
    for hash_seed in ("1", "2"):
        out = tmp_path / f"hashseed_{hash_seed}"
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        subprocess.run([sys.executable, "-c", script, str(out)], check=True, env=env)
        outputs.append(digests(out))
    assert outputs[0] == outputs[1]


def test_refuses_to_write_unsampled_spans(tmp_path: Path) -> None:
    unsampled = SpanRecord("", "", None, "a", 0, 1, False)
    with pytest.raises(ValueError, match="unsampled"):
        write_incident(tmp_path, {}, [], [unsampled], {"a": "op"}, {})
