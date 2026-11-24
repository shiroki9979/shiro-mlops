"""GitHub Actions workflows state their token permissions instead of inheriting the repo default.

The repository is public (ADR-0016): every job runs third-party actions and package installs,
so a job gets a write-scoped ``GITHUB_TOKEN`` or an OIDC token only where it says so. A job
that does get an OIDC token installs no packages, since any step in it can request the token.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
WORKFLOWS = sorted([*WORKFLOWS_DIR.glob("*.yml"), *WORKFLOWS_DIR.glob("*.yaml")])
READ_ONLY = {"contents": "read"}
# 只有這兩個 job 以 OIDC 取得 AWS 角色（docs/reference/terraform-state-and-deployment.md 第 3 節）。
JOBS_ASSUMING_AN_AWS_ROLE = {("ci.yml", "terraform-plan"), ("ci.yml", "deploy")}
# 持有 OIDC token 的 job 只能用這些 action；其餘第三方程式碼都能請求 token 或讀到匯出的 AWS_*。
ACTIONS_ALLOWED_WITH_AN_OIDC_TOKEN = {
    "actions/checkout",
    "actions/download-artifact",
    "aws-actions/configure-aws-credentials",
    "hashicorp/setup-terraform",
}
PACKAGE_INSTALLERS = re.compile(r"\b(?:pnpm|npm|npx|yarn|corepack|uvx?|pipx?|pip3)\b")
CALLED_SCRIPT = re.compile(r"\bscripts/[\w.-]+\.sh\b")


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


def _jobs_with_an_oidc_token() -> list[tuple[str, str, dict]]:
    return [
        (path.name, name, job)
        for path in WORKFLOWS
        for name, job in _load(path)["jobs"].items()
        if job.get("permissions", {}).get("id-token") == "write"
    ]


def _code_lines(script: Path) -> list[str]:
    lines = script.read_text(encoding="utf-8").splitlines()
    return [line for line in lines if not line.lstrip().startswith("#")]


def test_the_aws_jobs_are_the_jobs_with_an_oidc_token() -> None:
    assert {(workflow, name) for workflow, name, _ in _jobs_with_an_oidc_token()} == (
        JOBS_ASSUMING_AN_AWS_ROLE
    )


@pytest.mark.parametrize(
    "job",
    [
        pytest.param(job, id=f"{workflow}:{name}")
        for workflow, name, job in _jobs_with_an_oidc_token()
    ],
)
def test_a_job_with_an_oidc_token_installs_no_packages(job: dict) -> None:
    """A compromised npm or PyPI package could otherwise assume the job's AWS role (#369)."""
    actions = {step["uses"].split("@")[0] for step in job["steps"] if "uses" in step}
    commands = [step["run"] for step in job["steps"] if "run" in step]
    scripts = {
        REPO_ROOT / match for command in commands for match in CALLED_SCRIPT.findall(command)
    }
    installs = [
        line
        for line in [*commands, *(line for script in scripts for line in _code_lines(script))]
        if PACKAGE_INSTALLERS.search(line)
    ]

    assert actions <= ACTIONS_ALLOWED_WITH_AN_OIDC_TOKEN
    assert installs == []
