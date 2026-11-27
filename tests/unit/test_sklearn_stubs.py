"""The local scikit-learn stubs under stubs/ match the installed scikit-learn."""

import ast
import subprocess
import sys
from collections.abc import Callable

import numpy as np
import pytest
from sklearn.neural_network import MLPRegressor

from tests.source_scan import REPO_ROOT

NEURAL_NETWORK_STUB = REPO_ROOT / "stubs" / "sklearn" / "neural_network" / "__init__.pyi"


def test_stubbed_signatures_match_installed_sklearn() -> None:
    # stubtest compares every name the stubs declare with the runtime object; --ignore-missing-stub
    # skips the names they leave out, since the stubs only cover the API this repo calls. Without
    # stubs on mypy_path, mypy would read scikit-learn's own sources as the stubs and this would
    # pass by comparing them with themselves; `uv run mypy` fails on sklearn's missing types then.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy.stubtest",
            "--ignore-missing-stub",
            "--mypy-config-file",
            str(REPO_ROOT / "pyproject.toml"),
            "sklearn",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def _is_str(value: object) -> bool:
    return isinstance(value, str)


def _is_float_array_list(ndim: int) -> Callable[[object], bool]:
    def check(value: object) -> bool:
        return isinstance(value, list) and all(
            isinstance(item, np.ndarray) and item.ndim == ndim and item.dtype == np.float64
            for item in value
        )

    return check


# Keyed by the annotation text in the stub, so an attribute declared with a new type fails below
# until it gets a runtime check here.
RUNTIME_CHECKS = {
    "_Activation": _is_str,
    "str": _is_str,
    "_Weights": _is_float_array_list(ndim=2),
    "_Biases": _is_float_array_list(ndim=1),
}


def _stubbed_attributes() -> dict[str, str]:
    """Annotation text of each instance attribute the MLPRegressor stub declares."""
    module = ast.parse(NEURAL_NETWORK_STUB.read_text(encoding="utf-8"))
    regressor = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "MLPRegressor"
    )
    return {
        statement.target.id: ast.unparse(statement.annotation)
        for statement in regressor.body
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
    }


# stubtest cannot see these: sklearn sets them on the instance in __init__ and fit(), not on the
# class, so only a fitted regressor shows a renamed attribute or a changed array shape.
@pytest.mark.filterwarnings("ignore::sklearn.exceptions.ConvergenceWarning")
def test_stubbed_attributes_match_a_fitted_regressor() -> None:
    rng = np.random.default_rng(0)
    features = rng.normal(size=(20, 3))
    regressor = MLPRegressor(hidden_layer_sizes=(4,), max_iter=5, random_state=0)
    regressor.fit(features, features)

    declared = _stubbed_attributes()

    assert declared, f"no attributes found in {NEURAL_NETWORK_STUB}"
    mismatched = {
        name: annotation
        for name, annotation in declared.items()
        if not RUNTIME_CHECKS[annotation](getattr(regressor, name, None))
    }
    assert mismatched == {}
