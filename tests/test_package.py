"""Packaging contract: version, typing marker, stage layout and the lean-core rule."""

import importlib
import subprocess
import sys
from importlib import metadata, resources

import pytest

import tracehound

STAGE_PACKAGES = ["ingest", "detect", "correlate", "graph", "report", "sim", "bench"]

# Optional extras (`tracehound[ml]`, `tracehound[pandas]`): the core package must
# never import them, so a plain install stays lean.
OPTIONAL_HEAVY_MODULES = ["sklearn", "pandas"]


def test_version_matches_installed_metadata() -> None:
    assert tracehound.__version__ == metadata.version("tracehound")


def test_py_typed_marker_is_shipped() -> None:
    assert resources.files("tracehound").joinpath("py.typed").is_file()


@pytest.mark.parametrize("name", STAGE_PACKAGES)
def test_stage_package_is_importable_and_documented(name: str) -> None:
    module = importlib.import_module(f"tracehound.{name}")
    assert module.__doc__, f"tracehound.{name} needs a docstring explaining its stage"


def test_core_import_does_not_pull_optional_heavy_deps() -> None:
    # A fresh interpreter, so modules imported by pytest itself cannot leak in.
    imports = "; ".join(f"import tracehound.{name}" for name in STAGE_PACKAGES)
    probe = f"import sys, tracehound; {imports}; print(','.join(sorted(sys.modules)))"
    loaded = (
        subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
        .stdout.strip()
        .split(",")
    )
    leaked = [m for m in OPTIONAL_HEAVY_MODULES if m in loaded]
    assert leaked == [], f"core import pulled optional deps: {leaked}"
