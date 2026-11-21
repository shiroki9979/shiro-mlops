"""CLIs must print ``--help`` when docstrings are stripped (``python -OO``) or deleted."""

import subprocess
import sys
from pathlib import Path

import pytest

from shiro_mlops.pipelines import smoke_check

REPO_ROOT = Path(__file__).resolve().parents[2]
REDERIVE_DESCRIPTION = (
    "Derive hourly actual load for stored regional snapshots the scheduled asset never covered."
)
SMOKE_CHECK_DESCRIPTION = (
    "Container smoke check: schedule configuration, per-task readiness, and forecast issuing."
)


def _unwrapped(help_text: str) -> str:
    return " ".join(help_text.split())


@pytest.mark.parametrize(
    ("command", "description"),
    [
        pytest.param(
            ["scripts/rederive_hourly_actual_load.py"],
            REDERIVE_DESCRIPTION,
            id="rederive_hourly_actual_load",
        ),
        pytest.param(
            ["-m", "shiro_mlops.pipelines.smoke_check"],
            SMOKE_CHECK_DESCRIPTION,
            id="smoke_check",
            marks=pytest.mark.xfail(
                strict=True,
                reason=(
                    "lightgbm 4.7.0 crashes on import under -OO: lightgbm/dask.py calls "
                    "LGBMClassifier.__init__.__doc__.partition(), and shiro_mlops.pipelines "
                    "imports lightgbm before smoke_check parses arguments"
                ),
            ),
        ),
    ],
)
def test_help_starts_without_docstrings(command: list[str], description: str) -> None:
    result = subprocess.run(
        [sys.executable, "-OO", *command, "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert description in _unwrapped(result.stdout)


def test_smoke_check_help_starts_without_module_docstring(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(smoke_check, "__doc__", None)

    with pytest.raises(SystemExit) as exit_info:
        smoke_check.main(["--help"])

    assert exit_info.value.code == 0
    assert SMOKE_CHECK_DESCRIPTION in _unwrapped(capsys.readouterr().out)
