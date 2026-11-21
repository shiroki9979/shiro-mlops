"""Offline tests for scripts/check_aws_configured.sh, the skip step of the CI jobs that need AWS.

The script reads GitHub Actions' step output and job summary files from the environment, so the
tests point both at temporary files.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_aws_configured.sh"
VARIABLE = "AWS_TERRAFORM_PLAN_ROLE_ARN"


def _run(
    tmp_path: Path, *args: str, value: str | None = None
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    output = tmp_path / "output"
    summary = tmp_path / "summary.md"
    env = {key: item for key, item in os.environ.items() if key != VARIABLE} | {
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    if value is not None:
        env[VARIABLE] = value
    result = subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, check=False
    )

    def read(path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    return result, read(output), read(summary)


def test_unset_variable_skips_with_a_notice_and_a_summary_line(tmp_path: Path) -> None:
    result, output, summary = _run(tmp_path, VARIABLE, "Terraform plan")

    assert result.returncode == 0, result.stderr
    assert output == "configured=false\n"
    assert result.stdout == "::notice::AWS 尚未設定，略過 Terraform plan\n"
    assert summary == (
        f"AWS 尚未設定（repository variable `{VARIABLE}` 未設定），略過 Terraform plan。\n"
    )


def test_empty_variable_counts_as_unset(tmp_path: Path) -> None:
    result, output, _ = _run(tmp_path, VARIABLE, "Terraform plan", value="")

    assert result.returncode == 0, result.stderr
    assert output == "configured=false\n"


def test_set_variable_continues_without_a_summary(tmp_path: Path) -> None:
    result, output, summary = _run(
        tmp_path,
        VARIABLE,
        "Terraform plan",
        value="arn:aws:iam::123456789012:role/shiro-mlops-terraform-plan",
    )

    assert result.returncode == 0, result.stderr
    assert output == "configured=true\n"
    assert summary == ""


def test_rejects_wrong_argument_count(tmp_path: Path) -> None:
    result, output, _ = _run(tmp_path, VARIABLE)

    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert output == ""
