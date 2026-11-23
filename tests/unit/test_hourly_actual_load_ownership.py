"""ADR-0008: the hourly actual load store owns ``raw_taipower_load`` and its derived source.

Outside the store, SQL naming the table appears only in schema init and migration
(``src/shiro_mlops/core/database.py``) and in the forecast track-record join
(``src/shiro_mlops/data/forecast_track_record.py``). The Data
Explorer reaches the table through its declarative dataset definition, not SQL of its
own; it and the join bind the store's source constant rather than spelling the value.
Comments, docstrings and log text that name the table or the source are not SQL and pass.
"""

import ast
import re
from collections.abc import Callable

import pytest

from tests.source_scan import REPO_ROOT, SRC_DIR, scan_sources

STORE = "src/shiro_mlops/data/hourly_actual_load_store.py"
SCHEMA_SETUP = "src/shiro_mlops/core/database.py"
SCANNED_DIRS = (SRC_DIR, REPO_ROOT / "scripts", REPO_ROOT / "lab")
LOAD_TABLE_SQL = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+raw_taipower_load\b")
DERIVED_SOURCE = "regional_snapshot_sum"


def _load_table_sql_sites(source: str) -> list[str]:
    """Qualified names of the scopes holding SQL that reads or writes the load table."""
    sites: list[str] = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            scope = (*scope, node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            site = ".".join(scope) or "<module>"
            if LOAD_TABLE_SQL.search(node.value) and site not in sites:
                sites.append(site)
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(ast.parse(source), ())
    return sites


def _derived_source_spellings(source: str) -> list[int]:
    """Lines spelling the derived source as a value or inside a SQL string literal."""
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (node.value == DERIVED_SOURCE or f"'{DERIVED_SOURCE}'" in node.value)
    ]


def _scan(find: Callable[[str], list]) -> dict[str, list]:
    found: dict[str, list] = {}
    for directory in SCANNED_DIRS:
        found |= scan_sources(directory, lambda path, source: find(source))
    return found


def test_outside_the_store_only_schema_setup_and_track_record_join_touch_load_table() -> None:
    sites = _scan(_load_table_sql_sites)

    assert STORE in sites and SCHEMA_SETUP in sites
    del sites[STORE], sites[SCHEMA_SETUP]
    assert sites == {
        "src/shiro_mlops/data/forecast_track_record.py": ["ForecastTrackRecordStore.fetch_pairs"]
    }


def test_derived_source_value_is_spelled_once_in_the_store() -> None:
    spellings = _scan(_derived_source_spellings)

    assert {path: len(lines) for path, lines in spellings.items()} == {STORE: 1}


@pytest.mark.parametrize(
    ("source", "sites"),
    [
        ('q = "SELECT time FROM raw_taipower_load"', ["<module>"]),
        ('def read():\n    return f"SELECT * FROM raw_taipower_load WHERE {c}"', ["read"]),
        ('class R:\n    def write(self):\n        "INSERT INTO raw_taipower_load"', ["R.write"]),
        ('def join():\n    "... JOIN raw_taipower_load AS actual ON ..."', ["join"]),
        ('def migrate():\n    "UPDATE raw_taipower_load SET subject = :s"', ["migrate"]),
        ('def migrate():\n    "ALTER TABLE raw_taipower_load ADD COLUMN source"', ["migrate"]),
        ('message = "reads raw_taipower_load via the store"', []),
        ('message = "raw_taipower_load contains 3 legacy rows"', []),
        ('HOURLY_LOAD = Dataset(relation="raw_taipower_load")', []),
        ("# SELECT time FROM raw_taipower_load", []),
        ('q = "SELECT time FROM raw_taipower_load_archive"', []),
    ],
)
def test_load_table_scan_flags_sql_and_passes_other_mentions(source: str, sites: list[str]) -> None:
    assert _load_table_sql_sites(source) == sites


@pytest.mark.parametrize(
    ("source", "spelled"),
    [
        ('SOURCE = "regional_snapshot_sum"', True),
        ("q = \"SELECT * FROM t WHERE source = 'regional_snapshot_sum'\"", True),
        ('def f():\n    """Rows with a ``regional_snapshot_sum`` source."""', False),
        ('params = {"source": REGIONAL_SNAPSHOT_SUM_SOURCE}', False),
    ],
)
def test_derived_source_scan_flags_values_and_sql_literals(source: str, spelled: bool) -> None:
    assert bool(_derived_source_spellings(source)) is spelled
