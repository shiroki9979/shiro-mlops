"""Offline tests for scripts/plan_terraform.sh, the saved plan and safety check that the PR plan
and deploy jobs share (docs/reference/terraform-state-and-deployment.md).

A fake `terraform` executable on PATH records each invocation and prints a plan fixture from
tests/fixtures/terraform_plan/ for `show -json`, so the real scripts/check_plan_safety.py
judges it without Terraform, a state backend or AWS credentials.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "plan_terraform.sh"
PLAN_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "terraform_plan"
BACKEND_CONFIG = "bucket=shiro-mlops-tfstate-123456789012"

FAKE_TERRAFORM = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$TERRAFORM_CALL_LOG"
if [[ -n "${TERRAFORM_FAIL_ON:-}" && "$1" == "$TERRAFORM_FAIL_ON" ]]; then
  exit 3
fi
if [[ "$1" == "show" ]]; then
  cat "$TERRAFORM_PLAN_JSON"
fi
"""


def _run(
    tmp_path: Path, *args: str, plan: str = "create_only.json", fail_on: str | None = None
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake_terraform = bin_dir / "terraform"
    fake_terraform.write_text(FAKE_TERRAFORM, encoding="utf-8")
    fake_terraform.chmod(0o755)
    call_log = tmp_path / "terraform-calls.log"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "TERRAFORM_CALL_LOG": str(call_log),
        "TERRAFORM_PLAN_JSON": str(PLAN_FIXTURES / plan),
    }
    if fail_on is not None:
        env["TERRAFORM_FAIL_ON"] = fail_on
    result = subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, check=False
    )
    lines = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
    return result, [shlex.split(line) for line in lines]


def test_safe_plan_is_saved_exported_and_summarised_without_applying(tmp_path: Path) -> None:
    plan_file = tmp_path / "tfplan"
    summary = tmp_path / "summary.md"

    result, calls = _run(
        tmp_path, "--out", str(plan_file), "--summary", str(summary), BACKEND_CONFIG
    )

    assert result.returncode == 0, result.stderr
    assert calls == [
        ["init", "-input=false", "-reconfigure", f"-backend-config={BACKEND_CONFIG}"],
        ["plan", "-input=false", f"-out={plan_file}"],
        ["show", "-json", str(plan_file)],
    ]
    assert (tmp_path / "tfplan.json").read_text(encoding="utf-8") == (
        PLAN_FIXTURES / "create_only.json"
    ).read_text(encoding="utf-8")
    assert "Result: safe" in summary.read_text(encoding="utf-8")


def test_lock_false_is_passed_to_plan(tmp_path: Path) -> None:
    plan_file = tmp_path / "tfplan"

    result, calls = _run(tmp_path, "--lock=false", "--out", str(plan_file), BACKEND_CONFIG)

    assert result.returncode == 0, result.stderr
    assert ["plan", "-input=false", "-lock=false", f"-out={plan_file}"] in calls


def test_unsafe_plan_exits_1_and_still_writes_the_summary(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"

    result, calls = _run(
        tmp_path,
        "--out",
        str(tmp_path / "tfplan"),
        "--summary",
        str(summary),
        BACKEND_CONFIG,
        plan="delete.json",
    )

    assert result.returncode == 1
    assert "Result: unsafe" in summary.read_text(encoding="utf-8")
    assert all(call[0] != "apply" for call in calls)


def test_summary_goes_to_stdout_without_summary_file(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, "--out", str(tmp_path / "tfplan"), BACKEND_CONFIG)

    assert result.returncode == 0, result.stderr
    assert "## Terraform plan safety check" in result.stdout


@pytest.mark.parametrize(("failing", "expected_calls"), [("init", 1), ("plan", 2)])
def test_failing_terraform_command_stops_the_script_with_its_exit_code(
    tmp_path: Path, failing: str, expected_calls: int
) -> None:
    summary = tmp_path / "summary.md"

    result, calls = _run(
        tmp_path,
        "--out",
        str(tmp_path / "tfplan"),
        "--summary",
        str(summary),
        BACKEND_CONFIG,
        fail_on=failing,
    )

    assert result.returncode == 3
    assert [call[0] for call in calls][-1] == failing
    assert len(calls) == expected_calls
    assert not summary.exists()


@pytest.mark.parametrize(
    "args",
    [(), ("--lock=true", BACKEND_CONFIG), (BACKEND_CONFIG, "extra"), ("--out",)],
)
def test_rejects_bad_arguments_without_running_terraform(tmp_path: Path, args) -> None:
    result, calls = _run(tmp_path, *args)

    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert calls == []
