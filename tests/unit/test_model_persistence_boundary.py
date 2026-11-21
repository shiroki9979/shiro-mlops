"""ADR-0010: model files are never pickled.

No module under src/ may import pickle or joblib, and every ``np.load`` call must pass
``allow_pickle=False`` as a keyword.
"""

import ast
from pathlib import Path

import pytest

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


def _np_load_names(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Return the names bound to the numpy module and to ``numpy.load`` itself."""
    numpy_aliases: set[str] = set()
    load_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            numpy_aliases.update(
                alias.asname or alias.name for alias in node.names if alias.name == "numpy"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "numpy" and node.level == 0:
            load_aliases.update(
                alias.asname or alias.name for alias in node.names if alias.name == "load"
            )
    return numpy_aliases, load_aliases


def _passes_allow_pickle_false(call: ast.Call) -> bool:
    return any(
        keyword.arg == "allow_pickle"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is False
        for keyword in call.keywords
    )


def _np_load_calls_without_allow_pickle_false(source: str) -> list[int]:
    """Return the line numbers of ``np.load`` calls lacking keyword ``allow_pickle=False``."""
    tree = ast.parse(source)
    numpy_aliases, load_aliases = _np_load_names(tree)
    offending_lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_np_load = (
            isinstance(func, ast.Attribute)
            and func.attr == "load"
            and isinstance(func.value, ast.Name)
            and func.value.id in numpy_aliases
        ) or (isinstance(func, ast.Name) and func.id in load_aliases)
        if is_np_load and not _passes_allow_pickle_false(node):
            offending_lines.append(node.lineno)
    return offending_lines


def test_src_np_load_always_disables_pickle() -> None:
    offenders = {
        str(path.relative_to(SRC_DIR)): _np_load_calls_without_allow_pickle_false(
            path.read_text(encoding="utf-8")
        )
        for path in SRC_DIR.rglob("*.py")
    }

    assert {path: lines for path, lines in offenders.items() if lines} == {}


@pytest.mark.parametrize(
    "source",
    [
        "import numpy as np\nnp.load('a.npz')",
        "import numpy as np\nnp.load('a.npz', allow_pickle=True)",
        "import numpy as np\nnp.load('a.npz', None, False)",
        "import numpy as np\nnp.load('a.npz', **options)",
        "import numpy as np\nflag = False\nnp.load('a.npz', allow_pickle=flag)",
        "import numpy\nnumpy.load('a.npz')",
        "import numpy as xp\nxp.load('a.npz')",
        "from numpy import load\nload('a.npz')",
        "from numpy import load as np_load\nnp_load('a.npz')",
        "import numpy as np\ndef read(path):\n    with np.load(path) as arrays:\n        return arrays",
    ],
)
def test_np_load_scan_rejects_call_without_keyword_allow_pickle_false(source: str) -> None:
    assert _np_load_calls_without_allow_pickle_false(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "import numpy as np\nnp.load('a.npz', allow_pickle=False)",
        "import numpy as np\nnp.load('a.npz', mmap_mode='r', allow_pickle=False)",
        "from numpy import load\nload('a.npz', allow_pickle=False)",
        "import json\njson.load(handle)",
        "import numpy as np\nnp.save('a.npy', values)",
        "x = 'np.load(path)'",
    ],
)
def test_np_load_scan_allows_explicit_allow_pickle_false_and_other_loads(source: str) -> None:
    assert _np_load_calls_without_allow_pickle_false(source) == []
