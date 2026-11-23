"""GitHub Actions workflows state their token permissions instead of inheriting the repo default.

The repository is public (ADR-0016): every job runs third-party actions and package installs,
so a job gets a write-scoped ``GITHUB_TOKEN`` or an OIDC token only where it says so.
"""

from pathlib import Path

import pytest
import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"
WORKFLOWS = sorted([*WORKFLOWS_DIR.glob("*.yml"), *WORKFLOWS_DIR.glob("*.yaml")])
READ_ONLY = {"contents": "read"}
# 只有這兩個 job 以 OIDC 取得 AWS 角色（docs/reference/terraform-state-and-deployment.md 第 3 節）。
JOBS_ASSUMING_AN_AWS_ROLE = {("ci.yml", "terraform-plan"), ("ci.yml", "deploy")}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_workflows_are_found() -> None:
    assert [path.name for path in WORKFLOWS] == ["branch-flow.yml", "ci.yml"]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_workflow_token_defaults_to_read_only_or_nothing(path: Path) -> None:
    permissions = _load(path).get("permissions")

    assert permissions in ({}, READ_ONLY), (
        f"{path.name} must declare top-level `permissions` of at most contents: read; "
        "without it every job inherits the repository default, which may be read and write"
    )


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_only_the_aws_jobs_ask_for_more_than_the_workflow_default(path: Path) -> None:
    jobs = _load(path)["jobs"]

    widened = {
        (path.name, name): job["permissions"] for name, job in jobs.items() if "permissions" in job
    }

    assert set(widened) <= JOBS_ASSUMING_AN_AWS_ROLE
    for permissions in widened.values():
        assert permissions == {"contents": "read", "id-token": "write"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_no_workflow_runs_on_pull_request_target(path: Path) -> None:
    """That trigger runs with the base repository's secrets on code a fork controls."""
    # PyYAML reads the bare key `on` as the boolean True.
    document = _load(path)
    triggers = document.get("on", document.get(True))

    assert "pull_request_target" not in triggers
