"""Offline tests for the Terraform plan safety check in scripts/check_plan_safety.py.

Each test feeds `main()` a `terraform show -json` plan from tests/fixtures/terraform_plan/
and checks the exit code and the Markdown summary written to stdout.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from check_plan_safety import main

PLAN_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "terraform_plan"


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    exit_code = main(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def _run_fixture(name: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    exit_code, out, _ = _run([str(PLAN_FIXTURES / name)], capsys)
    return exit_code, out


def test_plan_without_changes_is_safe(capsys) -> None:
    exit_code, summary = _run_fixture("no_changes.json", capsys)

    assert exit_code == 0
    assert "Result: safe" in summary
    assert "| no-op | 2 |" in summary


def test_plan_that_only_creates_and_reads_is_safe_and_lists_addresses(capsys) -> None:
    exit_code, summary = _run_fixture("create_only.json", capsys)

    assert exit_code == 0
    assert "Result: safe" in summary
    assert "| create | 2 |" in summary
    assert "| read | 1 |" in summary
    assert "### create (2)" in summary
    assert "- `aws_s3_bucket.forecast_view`" in summary
    assert "- `aws_cloudfront_distribution.forecast_view`" in summary
    assert "### read (1)" in summary
    assert "- `data.aws_caller_identity.current`" in summary


def test_plan_that_updates_in_place_is_safe(capsys) -> None:
    exit_code, summary = _run_fixture("update_in_place.json", capsys)

    assert exit_code == 0
    assert "Result: safe" in summary
    assert "| update | 1 |" in summary
    assert "- `aws_cloudfront_distribution.forecast_view`" in summary


def _violation_lines(summary: str) -> list[str]:
    section = summary.split("### Violations", 1)[1].split("\n### ", 1)[0]
    return [line for line in section.splitlines() if line.startswith("- ")]


def test_plan_that_deletes_is_unsafe_and_names_the_resource(capsys) -> None:
    exit_code, summary = _run_fixture("delete.json", capsys)

    assert exit_code == 1
    assert "Result: unsafe" in summary
    assert "| delete | 1 |" in summary
    assert _violation_lines(summary) == ["- `aws_budgets_budget.monthly`: delete"]
    assert "by a person on a local machine" in summary


@pytest.mark.parametrize(
    ("fixture", "action"),
    [
        ("replace_delete_before_create.json", "replace (delete, then create)"),
        ("replace_create_before_delete.json", "replace (create, then delete)"),
    ],
)
def test_plan_that_replaces_is_unsafe_in_either_order(fixture, action, capsys) -> None:
    exit_code, summary = _run_fixture(fixture, capsys)

    assert exit_code == 1
    assert "Result: unsafe" in summary
    assert f"| {action} | 1 |" in summary
    assert _violation_lines(summary) == [f"- `aws_cloudfront_distribution.forecast_view`: {action}"]


def test_plan_that_forgets_is_unsafe(capsys) -> None:
    exit_code, summary = _run_fixture("forget.json", capsys)

    assert exit_code == 1
    assert "Result: unsafe" in summary
    assert _violation_lines(summary) == ["- `aws_iam_user.publisher`: forget"]


def test_plan_with_several_violations_lists_each_one(capsys) -> None:
    exit_code, summary = _run_fixture("multiple_violations.json", capsys)

    assert exit_code == 1
    assert "Result: unsafe**: 3 resource change(s)" in summary
    assert _violation_lines(summary) == [
        "- `aws_cloudfront_distribution.forecast_view`: replace (delete, then create)",
        "- `aws_budgets_budget.monthly`: delete",
        "- `aws_iam_user.publisher`: forget",
    ]
    assert "| update | 1 |" in summary
    assert "| create | 1 |" in summary


def test_unparseable_json_exits_2(tmp_path, capsys) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text('{"resource_changes": [', encoding="utf-8")

    exit_code, out, err = _run([str(plan)], capsys)

    assert exit_code == 2
    assert out == ""
    assert "not valid JSON" in err


def test_json_that_is_not_a_plan_exits_2(tmp_path, capsys) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text('{"resource_changes": [{"address": "aws_s3_bucket.x"}]}', encoding="utf-8")

    exit_code, out, err = _run([str(plan)], capsys)

    assert exit_code == 2
    assert out == ""
    assert "not a `terraform show -json` plan" in err


def test_missing_plan_file_exits_2(tmp_path, capsys) -> None:
    exit_code, out, err = _run([str(tmp_path / "absent.json")], capsys)

    assert exit_code == 2
    assert out == ""
    assert "cannot read" in err


def test_missing_argument_exits_2(capsys) -> None:
    exit_code, out, err = _run([], capsys)

    assert exit_code == 2
    assert out == ""
    assert "plan_json" in err
