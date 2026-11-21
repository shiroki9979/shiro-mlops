"""Every Dagster asset declares its UI description, so it never falls back to the function docstring."""

import ast
import textwrap
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
ASSET_DECORATORS = frozenset({"asset", "multi_asset"})


def _asset_decorators(source: str) -> list[tuple[int, bool]]:
    """(line, passes ``description=``) for each ``@asset`` / ``@multi_asset`` decorator."""
    found: list[tuple[int, bool]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            target = call.func if call else decorator
            name = getattr(target, "id", None) or getattr(target, "attr", None)
            if name in ASSET_DECORATORS:
                keywords = {keyword.arg for keyword in call.keywords} if call else set()
                found.append((decorator.lineno, "description" in keywords))
    return found


def test_every_src_asset_decorator_passes_a_description() -> None:
    decorators = {
        str(path.relative_to(SRC_DIR)): _asset_decorators(path.read_text(encoding="utf-8"))
        for path in SRC_DIR.rglob("*.py")
    }

    assert sum(len(found) for found in decorators.values()) > 0
    missing = {
        path: [line for line, described in found if not described]
        for path, found in decorators.items()
    }
    assert {path: lines for path, lines in missing.items() if lines} == {}


@pytest.mark.parametrize(
    "decorator",
    [
        "@asset",
        "@asset()",
        '@asset(group_name="features")',
        "@dagster.asset(io_manager_key='x')",
        "@multi_asset(outs={})",
        "@dg.multi_asset",
    ],
)
def test_an_asset_decorator_without_description_is_reported(decorator: str) -> None:
    source = textwrap.dedent(
        f"""
        {decorator}
        def some_asset():
            '''Docstring the Dagster UI must not fall back to.'''
        """
    )

    assert _asset_decorators(source) == [(2, False)]


@pytest.mark.parametrize(
    "decorator",
    ['@asset(description="Fetch")', '@dagster.multi_asset(outs={}, description="Export")'],
)
def test_an_asset_decorator_with_description_passes(decorator: str) -> None:
    source = f"{decorator}\ndef some_asset():\n    pass\n"

    assert _asset_decorators(source) == [(1, True)]


def test_decorators_other_than_assets_are_ignored() -> None:
    source = "@op\n@schedule(cron_schedule='0 * * * *')\ndef job():\n    pass\n"

    assert _asset_decorators(source) == []
