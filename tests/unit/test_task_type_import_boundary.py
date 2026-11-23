"""ADR-0009: task types never touch the data layer and never see Dagster or Feast.

Direct imports are scanned, because package initialisers still pull in Dagster at runtime
and a check on loaded modules would fail for reasons outside task types. Feast is the
exception: nothing a task type, the API or a Dagster step imports may load it, so that one
is checked on the modules a fresh interpreter ends up with.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from tests.source_scan import SRC_DIR, scan_sources

TASK_TYPES_DIR = SRC_DIR / "shiro_mlops" / "tasks" / "types"
FORBIDDEN_PREFIXES = (
    "shiro_mlops.data",
    "shiro_mlops.core.database",
    "sqlalchemy",
    "dagster",
    "feast",
)


def _is_forbidden(module: str) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in FORBIDDEN_PREFIXES)


def _resolve_relative(module: str | None, level: int, package: str) -> str:
    base = package.split(".")
    if level > 1:
        base = base[: -(level - 1)]
    return ".".join([*base, module] if module else base)


def _forbidden_imports(source: str, package: str) -> list[str]:
    """Return the forbidden modules ``source`` imports directly, resolved against ``package``."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names if _is_forbidden(alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = (
                _resolve_relative(node.module, node.level, package)
                if node.level
                else node.module or ""
            )
            candidates = [module, *(f"{module}.{alias.name}" for alias in node.names)]
            found.extend(candidate for candidate in candidates if _is_forbidden(candidate))
    return found


def _package_of(path: Path) -> str:
    return ".".join(path.parent.relative_to(SRC_DIR).parts)


def test_task_types_never_import_data_layer_sqlalchemy_dagster_or_feast() -> None:
    offenders = scan_sources(
        TASK_TYPES_DIR, lambda path, source: _forbidden_imports(source, _package_of(path))
    )

    assert offenders == {}


@pytest.mark.parametrize(
    "source",
    [
        "import dagster",
        "from dagster import asset",
        "import feast.types",
        "from feast import FeatureStore",
        "from sqlalchemy.engine import Engine",
        "import shiro_mlops.data.repository",
        "from shiro_mlops.data.repository import TimescaleRepository",
        "from shiro_mlops import data",
        "from shiro_mlops.core import database",
        "from shiro_mlops.core.database import get_engine",
        "from ...data import repository",
        "from ...core import database",
        "def train():\n    import dagster\n",
    ],
)
def test_scan_rejects_forbidden_direct_import(source: str) -> None:
    assert _forbidden_imports(source, "shiro_mlops.tasks.types") != []


@pytest.mark.parametrize(
    "source",
    [
        "import pandas as pd",
        "from shiro_mlops.core.constants import DATETIME_COL",
        "from shiro_mlops.core import constants",
        "from shiro_mlops.features.transformers import create_calendar_features",
        "from shiro_mlops.tasks.types.base import TaskType",
        "from . import base",
        "from .metadata import ModelFormat",
        "import dagster_like_but_not_dagster",
        "x = 'import dagster'",
    ],
)
def test_scan_allows_imports_outside_the_boundary(source: str) -> None:
    assert _forbidden_imports(source, "shiro_mlops.tasks.types") == []


@pytest.mark.parametrize(
    "module",
    [
        "shiro_mlops.features",
        "shiro_mlops.tasks.types",
        "shiro_mlops.service.api",
        "shiro_mlops.pipelines.definitions",
    ],
)
def test_importing_the_runtime_entry_points_does_not_load_feast(module: str) -> None:
    """Feast costs over a second to import and every Dagster step process would pay it."""
    probe = f"import sys, {module}; sys.exit('feast' in sys.modules)"

    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
