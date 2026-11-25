"""Repository rules that keep the codebase small and readable: no code file over 200 lines."""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_LINES_PER_FILE = 200
CODE_SUFFIXES = {".py", ".toml", ".yml", ".yaml", ".cfg", ".ini", ".sh"}
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "build",
    "dist",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
}


def code_files() -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        found.extend(Path(dirpath, f) for f in sorted(filenames) if Path(f).suffix in CODE_SUFFIXES)
    return found


def test_rule_actually_sees_files() -> None:
    # Guards against the walk silently matching nothing (which would pass every check).
    names = {p.name for p in code_files()}
    assert {"pyproject.toml", "test_repo_rules.py", "__init__.py"} <= names


@pytest.mark.parametrize("path", code_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_code_file_is_at_most_200_lines(path: Path) -> None:
    n_lines = len(path.read_text(encoding="utf-8").splitlines())
    assert n_lines <= MAX_LINES_PER_FILE, (
        f"{path.relative_to(REPO_ROOT)} has {n_lines} lines; split it into smaller modules"
    )
