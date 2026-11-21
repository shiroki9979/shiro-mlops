"""Scan the Python modules under src/ for architecture-boundary tests."""

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")
SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def scan_sources(directory: Path, find: Callable[[Path, str], list[T]]) -> dict[str, list[T]]:
    """Run ``find(path, source)`` on each module under ``directory``; return the files it flags.

    Keys are paths relative to src/. Raises AssertionError when ``directory`` has no
    modules, so a moved package cannot make a boundary test pass vacuously.
    """
    paths = sorted(directory.rglob("*.py"))
    assert paths, f"no Python modules under {directory}; the scan would pass vacuously"
    found = {
        str(path.relative_to(SRC_DIR)): find(path, path.read_text(encoding="utf-8"))
        for path in paths
    }
    return {path: items for path, items in found.items() if items}
