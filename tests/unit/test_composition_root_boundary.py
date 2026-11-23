"""#233: ``TimeSeriesRepository`` is a composition root, imported only where stores are wired.

Its module exports nothing but the root, so every store is imported from its own module.
In ``src`` only the entry points that build the root or hand it out import it; the runner,
the served tasks and the Data Explorer receive stores or an engine instead.
"""

import ast

import pytest

from tests.source_scan import REPO_ROOT, SRC_DIR, scan_sources

FACADE_MODULE = "shiro_mlops.data.repository"
FACADE = "TimeSeriesRepository"
DATA_PACKAGE = "shiro_mlops.data"
COMPOSITION_SITES = {
    "src/shiro_mlops/data/__init__.py",
    "src/shiro_mlops/pipelines/definitions.py",
    "src/shiro_mlops/pipelines/smoke_check.py",
    "src/shiro_mlops/service/api.py",
}
SCANNED_DIRS = (SRC_DIR, REPO_ROOT / "scripts", REPO_ROOT / "lab", REPO_ROOT / "tests")


def _facade_imports(source: str) -> list[str]:
    """Each name imported from the facade module, or the root imported through the package."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names if alias.name == FACADE_MODULE)
        elif isinstance(node, ast.ImportFrom) and node.module == FACADE_MODULE:
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module == DATA_PACKAGE:
            found.extend(
                f"{DATA_PACKAGE}.{alias.name}"
                for alias in node.names
                if alias.name in {FACADE, "repository"}
            )
    return found


def test_the_facade_module_hands_out_only_the_composition_root() -> None:
    """Stores are imported from their own modules, never re-exported through the facade."""
    reexported: dict[str, list[str]] = {}
    for directory in SCANNED_DIRS:
        reexported |= scan_sources(
            directory,
            lambda path, source: [
                name
                for name in _facade_imports(source)
                if name not in {FACADE, FACADE_MODULE, f"{DATA_PACKAGE}.{FACADE}"}
            ],
        )

    assert reexported == {}


def test_only_composition_sites_in_src_import_the_composition_root() -> None:
    importers = scan_sources(SRC_DIR, lambda path, source: _facade_imports(source))

    assert set(importers) <= COMPOSITION_SITES


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from shiro_mlops.data.repository import TimeSeriesRepository", [FACADE]),
        (
            "from shiro_mlops.data.repository import IssuedForecastRepository",
            ["IssuedForecastRepository"],
        ),
        ("import shiro_mlops.data.repository", [FACADE_MODULE]),
        ("from shiro_mlops.data import TimeSeriesRepository", [f"{DATA_PACKAGE}.{FACADE}"]),
        ("from shiro_mlops.data import repository", [f"{DATA_PACKAGE}.repository"]),
        (
            "def wire():\n    from shiro_mlops.data.repository import TimeSeriesRepository\n",
            [FACADE],
        ),
        ("from shiro_mlops.data import CWAClient", []),
        ("from shiro_mlops.data.cwa_weather_store import CWAWeatherStore", []),
        ("x = 'from shiro_mlops.data.repository import TimeSeriesRepository'", []),
    ],
)
def test_scan_finds_facade_imports(source: str, expected: list[str]) -> None:
    assert _facade_imports(source) == expected
