"""Offline doc-dates tests against throwaway git repositories built in tmp_path."""

import os
import subprocess
from pathlib import Path

import check_conventions
import pytest
from check_conventions import GitRange, check_doc_dates, main


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Doc Author")
    _git(tmp_path, "config", "user.email", "doc-author@example.com")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


def _git(repo: Path, *args: str, extra_env: dict[str, str] | None = None) -> str:
    env = {**os.environ, **(extra_env or {})}
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env
    )
    return result.stdout


def _commit(repo: Path, files: dict[str, str | None], authored_on: str) -> str:
    """Write (or delete, when None) files and commit them with the given author date.

    Committer dates stay at the real clock, as after a rebase, so log order follows ancestry
    rather than author dates.
    """
    for path, text in files.items():
        target = repo / path
        if text is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    author_date = {"GIT_AUTHOR_DATE": f"{authored_on}T12:00:00+08:00"}
    _git(repo, "commit", "-q", "-m", f"change on {authored_on}", extra_env=author_date)
    return _git(repo, "rev-parse", "HEAD").strip()


def _doc(updated_on: str, body: str = "Body.") -> str:
    return f"# Guide\n\n- 最後更新：{updated_on}\n\n{body}\n"


def _locations(violations) -> list[tuple[str, int]]:
    return [(violation.path, violation.line) for violation in violations]


def test_newest_author_date_is_used_even_when_an_older_commit_comes_last(repo: Path) -> None:
    base = _commit(repo, {"docs/guide.md": _doc("2026-10-01")}, "2026-10-01")
    _commit(repo, {"docs/guide.md": _doc("2026-10-01", "Revised.")}, "2026-10-27")
    head = _commit(repo, {"docs/guide.md": _doc("2026-10-26", "Revised.")}, "2026-10-26")

    violations = check_doc_dates(GitRange(repo, base, head))

    assert _locations(violations) == [("docs/guide.md", 3)]


def test_same_day_edits_after_updating_the_header_pass(repo: Path) -> None:
    base = _commit(repo, {"docs/guide.md": _doc("2026-10-01")}, "2026-10-01")
    _commit(repo, {"docs/guide.md": _doc("2026-10-25")}, "2026-10-25")
    head = _commit(repo, {"docs/guide.md": _doc("2026-10-25", "Revised.")}, "2026-10-25")

    assert check_doc_dates(GitRange(repo, base, head)) == []


def test_changed_doc_without_header_is_a_violation(repo: Path) -> None:
    base = _commit(repo, {"docs/notes.md": "# Notes\n"}, "2026-10-01")
    head = _commit(repo, {"docs/notes.md": "# Notes\n\nMore.\n"}, "2026-10-25")

    violations = check_doc_dates(GitRange(repo, base, head))

    assert _locations(violations) == [("docs/notes.md", 1)]


def test_renamed_doc_must_update_its_header(repo: Path) -> None:
    base = _commit(repo, {"docs/old.md": _doc("2026-10-01")}, "2026-10-01")
    head = _commit(repo, {"docs/old.md": None, "docs/new.md": _doc("2026-10-01")}, "2026-10-25")

    violations = check_doc_dates(GitRange(repo, base, head))

    assert _locations(violations) == [("docs/new.md", 3)]


def test_deleted_doc_is_not_checked(repo: Path) -> None:
    base = _commit(repo, {"docs/guide.md": _doc("2026-10-01")}, "2026-10-01")
    head = _commit(repo, {"docs/guide.md": None}, "2026-10-25")

    assert check_doc_dates(GitRange(repo, base, head)) == []


def test_lab_markdown_is_excluded_from_doc_dates(repo: Path) -> None:
    base = _commit(repo, {"docs/guide.md": _doc("2026-10-01")}, "2026-10-01")
    head = _commit(
        repo,
        {"lab/2026-11-08-dhf-hyperparameter-search/README.md": "# Topic\n\nNo date header.\n"},
        "2026-11-08",
    )

    assert check_doc_dates(GitRange(repo, base, head)) == []


def test_main_exits_1_when_a_changed_doc_is_stale(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    base = _commit(repo, {"docs/guide.md": _doc("2026-10-01")}, "2026-10-01")
    head = _commit(repo, {"docs/guide.md": _doc("2026-10-01", "Revised.")}, "2026-10-25")

    assert main(["doc-dates", "--base", base, "--head", head]) == 1


def test_main_exits_0_when_changed_docs_are_current(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    base = _commit(repo, {"docs/guide.md": _doc("2026-10-01")}, "2026-10-01")
    head = _commit(repo, {"docs/guide.md": _doc("2026-10-25", "Revised.")}, "2026-10-25")

    assert main(["doc-dates", "--base", base, "--head", head]) == 0


def test_main_exits_2_when_base_ref_cannot_be_resolved(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    _commit(repo, {"docs/guide.md": _doc("2026-10-01")}, "2026-10-01")

    assert main(["doc-dates", "--base", "missing-ref"]) == 2


def test_doc_dates_without_base_exits_2() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["doc-dates"])

    assert exit_info.value.code == 2
