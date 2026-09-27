"""ADR-0010: model files are never pickled, so no module under src/ may import pickle or joblib."""

import ast
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
FORBIDDEN_MODULES = frozenset({"pickle", "joblib"})


def _imported_top_level_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    return modules


def test_src_never_imports_pickle_or_joblib() -> None:
    offenders = {
        str(path.relative_to(SRC_DIR)): sorted(
            _imported_top_level_modules(path) & FORBIDDEN_MODULES
        )
        for path in SRC_DIR.rglob("*.py")
    }

    assert {path: modules for path, modules in offenders.items() if modules} == {}
