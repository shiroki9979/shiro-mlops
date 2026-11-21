"""Offline tests for scripts/upload_forecast_view_site.sh, the CD upload of the Forecast View.

A fake `aws` executable on PATH records each invocation, so the tests check the upload order
contract of hosting spec §5 (docs/reference/forecast-view-hosting.md) without AWS credentials.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "upload_forecast_view_site.sh"
BUCKET = "shiro-mlops-forecast-view"

FAKE_AWS = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$AWS_CALL_LOG"
if [[ -n "${AWS_FAIL_ON:-}" && "$*" == *"$AWS_FAIL_ON"* ]]; then
  exit 1
fi
"""


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    built = tmp_path / "dist"
    (built / "assets").mkdir(parents=True)
    (built / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (built / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    return built


def _run(
    tmp_path: Path, *args: str, fail_on: str | None = None
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake_aws = bin_dir / "aws"
    fake_aws.write_text(FAKE_AWS, encoding="utf-8")
    fake_aws.chmod(0o755)
    call_log = tmp_path / "aws-calls.log"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "AWS_CALL_LOG": str(call_log),
    }
    if fail_on is not None:
        env["AWS_FAIL_ON"] = fail_on
    result = subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, check=False
    )
    calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
    return result, calls


def test_uploads_assets_before_index_html_and_then_deletes_old_assets(
    tmp_path: Path, dist: Path
) -> None:
    result, calls = _run(tmp_path, str(dist), BUCKET)

    assert result.returncode == 0, result.stderr
    site = f"s3://{BUCKET}/site/"
    assert [shlex.split(call) for call in calls] == [
        ["s3", "sync", f"{dist}/", site, "--exclude", "index.html", "--no-progress"],
        ["s3", "cp", f"{dist}/index.html", f"{site}index.html", "--no-progress"],
        ["s3", "sync", f"{dist}/", site, "--delete", "--no-progress"],
    ]


def test_refuses_a_build_without_index_html_so_sync_delete_cannot_empty_the_site(
    tmp_path: Path, dist: Path
) -> None:
    (dist / "index.html").unlink()

    result, calls = _run(tmp_path, str(dist), BUCKET)

    assert result.returncode == 2
    assert "index.html" in result.stderr
    assert calls == []


def test_stops_before_index_html_when_the_asset_upload_fails(tmp_path: Path, dist: Path) -> None:
    result, calls = _run(tmp_path, str(dist), BUCKET, fail_on="--exclude index.html")

    assert result.returncode != 0
    assert len(calls) == 1


def test_rejects_wrong_argument_count(tmp_path: Path, dist: Path) -> None:
    result, calls = _run(tmp_path, str(dist))

    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert calls == []
