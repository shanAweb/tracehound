"""``make_incident``: writes the hand-written sample incident, with any file replaced."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.ingest.sample import GROUND_TRUTH, META, METRIC_LINES, SPAN_RECORDS

MakeIncident = Callable[..., Path]


@pytest.fixture
def make_incident(tmp_path: Path) -> MakeIncident:
    """Write the sample folder, replacing a file's content with the argument given.

    ``meta`` and ``ground_truth`` are dicts (or raw text); ``metrics`` and ``traces`` are lists
    of lines. ``ground_truth=None`` leaves that optional file out.
    """

    def build(
        meta: dict[str, object] | str = META,
        metrics: list[str] = METRIC_LINES,
        traces: list[str] | None = None,
        ground_truth: dict[str, object] | str | None = GROUND_TRUTH,
    ) -> Path:
        folder = tmp_path / "incident"
        folder.mkdir(exist_ok=True)
        lines = [json.dumps(r) for r in SPAN_RECORDS] if traces is None else traces
        (folder / "meta.json").write_text(_json(meta))
        (folder / "metrics.csv").write_text("".join(f"{line}\n" for line in metrics))
        (folder / "traces.jsonl").write_text("".join(f"{line}\n" for line in lines))
        if ground_truth is not None:
            (folder / "ground_truth.json").write_text(_json(ground_truth))
        return folder

    return build


def _json(value: dict[str, object] | str) -> str:
    return value if isinstance(value, str) else json.dumps(value, indent=2)
