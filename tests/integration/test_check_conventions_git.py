"""Offline convention-check tests against throwaway git repositories built in tmp_path."""

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


def test_main_flags_a_tracked_source_debt_marker_without_an_issue(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    _commit(repo, {"src/pkg/load.py": "# TODO: retry on timeout\n"}, "2026-11-16")

    assert main(["debt-markers"]) == 1


def test_main_passes_once_the_debt_marker_names_its_issue(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    _commit(repo, {"src/pkg/load.py": "# TODO(#123): retry on timeout\n"}, "2026-11-16")

    assert main(["debt-markers"]) == 0


def test_comment_refs_fails_on_a_comment_path_that_does_not_exist(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    _commit(
        repo,
        {
            "docs/guide.md": "# Guide\n",
            "src/pkg/load.py": "x = 1\n# keep in sync with docs/missing.md\n",
        },
        "2026-11-21",
    )

    assert main(["comment-refs"]) == 1
    assert "src/pkg/load.py:2: " in capsys.readouterr().err


def test_comment_refs_passes_on_existing_paths_and_ignores_paths_in_strings(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    source = (
        "# Mirrors docs/guide.md and the files under docs/.\n"
        'MISSING = "docs/missing.md"  # Read from src/pkg/load.py.\n'
        "HELP = '''\n# docs/also-missing.md is text, not a comment\n'''\n"
    )
    _commit(repo, {"docs/guide.md": "# Guide\n", "src/pkg/load.py": source}, "2026-11-21")

    assert main(["comment-refs"]) == 0


def test_comment_refs_fails_on_an_adr_number_without_an_adr(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    source = "# Native formats only (ADR-0001).\nx = 1  # See ADR-0002.\n"
    _commit(
        repo,
        {"docs/adr/0001-native-formats.md": "# ADR\n", "src/pkg/load.py": source},
        "2026-11-21",
    )

    assert main(["comment-refs"]) == 1
    err = capsys.readouterr().err
    assert "src/pkg/load.py:2: " in err
    assert "src/pkg/load.py:1: " not in err


def test_comment_refs_skips_globs_placeholders_and_section_numbers(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    source = (
        "# Studies live under lab/<YYYY-MM-DD>-<topic>/ and match lab/drafts/*.py.\n"
        "# Each writes docs/{name}.md and scripts/${TOOL}.sh; see docs/guide.md 第 6 節.\n"
    )
    _commit(
        repo,
        {"docs/guide.md": "# Guide\n", "lab/run.py": "", "src/pkg/load.py": source},
        "2026-11-21",
    )

    assert main(["comment-refs"]) == 0


def _comment_kinds(repo: Path, before: dict[str, str], after: dict[str, str | None]) -> int:
    """Commit `before`, then `after`, and run comment-kinds over the second commit."""
    base = _commit(repo, before, "2026-11-21")
    head = _commit(repo, after, "2026-11-21")
    return main(["comment-kinds", "--base", base, "--head", head])


def test_comment_kinds_fails_on_an_added_untagged_comment(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    before = {"src/pkg/load.py": "x = 1\n"}
    after = {"src/pkg/load.py": "x = 1\n# --- helpers ---\ny = 2\n"}

    assert _comment_kinds(repo, before, after) == 1
    err = capsys.readouterr().err
    assert "src/pkg/load.py:2: " in err
    assert "WHY-NOT(<name>): <reason>" in err


def test_comment_kinds_passes_when_legacy_comments_are_left_untouched(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    legacy = "# Load the rows.\nx = 1  # one row\n"
    before = {"src/pkg/load.py": legacy}
    after = {"src/pkg/load.py": legacy + "y = 2\n"}

    assert _comment_kinds(repo, before, after) == 0


def test_comment_kinds_fails_when_a_modified_line_keeps_its_legacy_trailing_comment(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    before = {"src/pkg/load.py": "x = 1\nretries = 3  # retry a few times\n"}
    after = {"src/pkg/load.py": "x = 1\nretries = 5  # retry a few times\n"}

    assert _comment_kinds(repo, before, after) == 1
    assert "src/pkg/load.py:2: " in capsys.readouterr().err


def test_comment_kinds_needs_a_tag_only_on_the_first_line_of_a_block(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    block = (
        "def load():\n"
        "    # WHY-NOT(retries): the upstream rate limit resets every minute, so retrying\n"
        "    # faster only burns the quota.\n"
        "    retries = 3\n"
    )
    before = {"src/pkg/load.py": "x = 1\n"}
    after = {"src/pkg/load.py": "x = 1\n" + block}

    assert _comment_kinds(repo, before, after) == 0


def test_comment_kinds_checks_a_whole_legacy_block_when_one_of_its_lines_changes(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    before = {"src/pkg/load.py": "# Load the rows\n# from the cache.\nx = 1\n"}
    after = {"src/pkg/load.py": "# Load the rows\n# from the warm cache.\nx = 1\n"}

    assert _comment_kinds(repo, before, after) == 1
    assert "src/pkg/load.py:1: " in capsys.readouterr().err


def test_comment_kinds_starts_a_new_block_after_a_blank_line_or_an_indent_change(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    source = (
        "# WHY-NOT(load): rows stay lazy because the cache is larger than memory.\n"
        "\n"
        "# Loads rows.\n"
        "def load():\n"
        "    # TODO(#12): stream instead of batching.\n"
        "        # Batch size.\n"
        "    return 1\n"
    )
    before = {"src/pkg/load.py": "x = 1\n"}
    after = {"src/pkg/load.py": source}

    assert _comment_kinds(repo, before, after) == 1
    err = capsys.readouterr().err
    assert "src/pkg/load.py:3: " in err
    assert "src/pkg/load.py:6: " in err
    assert "src/pkg/load.py:1: " not in err
    assert "src/pkg/load.py:5: " not in err


def test_comment_kinds_passes_every_allowed_kind(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    source = (
        "# ruff: noqa: E501\n"
        "# WHY-NOT(retry.policy): 重試間隔加總必須小於 10 分鐘 slot，否則會和下一輪排程重疊\n"
        "policy = retry.policy\n"
        "# SYNC(scripts/smoke_nginx.py, docs/guide.md): 發布檔名清單刻意重複\n"
        "NAMES = ()\n"
        "# TODO(#42): read the names from the manifest.\n"
        "def Load():  # noqa: N802 — 名稱由 #66 的介面設計固定\n"
        "    return x  # type: ignore[name-defined]  # x comes from a star import\n"
        "# fmt: off\n"
        "GRID = [1,0,\n"
        "        0,1]\n"
        "# fmt: on\n"
        "if DEBUG:  # pragma: no cover\n"
        "    pass\n"
    )
    before = {"src/pkg/load.py": "x = 1\n"}
    after = {"src/pkg/load.py": source}

    assert _comment_kinds(repo, before, after) == 0


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("x = 1  # noqa: E741\n", "`noqa: E741` needs a reason"),
        ("x = 1  # noqa\n", "`noqa` needs a reason"),
        ("x = 1  # type: ignore[assignment]\n", "`type: ignore[assignment]` needs a reason"),
        ("# WHY-NOT(x)\nx = 1\n", "WHY-NOT(<name>): <reason>"),
        ("# WHY-NOT: x stays one\nx = 1\n", "WHY-NOT(<name>): <reason>"),
        ("# SYNC(): keep in step\nx = 1\n", "SYNC(<path>[, <path>...]): <note>"),
        ("# SYNC(docs/guide.md):\n# note below\nx = 1\n", "SYNC(<path>[, <path>...]): <note>"),
        ("# why-not(x): lower case is not a tag\nx = 1\n", "allowed kind"),
        ("# TODO: no issue\nx = 1\n", "allowed kind"),
    ],
)
def test_comment_kinds_fails_on_malformed_tags_and_unexplained_suppressions(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    line: str,
    expected: str,
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    before = {"src/pkg/load.py": "y = 2\n"}
    after = {"src/pkg/load.py": "y = 2\n" + line}

    assert _comment_kinds(repo, before, after) == 1
    err = capsys.readouterr().err
    assert "src/pkg/load.py:2: " in err
    assert expected in err


def test_comment_kinds_ignores_files_outside_the_package_and_scripts(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    untagged = "# Arrange\nx = 1\n"
    before = {"README.md": "# Repo\n"}
    after = {
        "tests/unit/test_load.py": untagged,
        "lab/2026-11-17-topic/study.py": untagged,
        "scripts/build.sh": untagged,
        "docs/conf.py": untagged,
    }

    assert _comment_kinds(repo, before, after) == 0


def test_comment_kinds_checks_scripts_too(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    before = {"README.md": "# Repo\n"}
    after = {"scripts/report.py": "# Print the report.\nprint(1)\n"}

    assert _comment_kinds(repo, before, after) == 1
    assert "scripts/report.py:1: " in capsys.readouterr().err


def test_comment_kinds_follows_renames_instead_of_rechecking_every_comment(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    legacy = "".join(f"# Legacy note {n}.\nvalue_{n} = {n}\n" for n in range(10))
    before = {"src/pkg/old.py": legacy}
    after = {"src/pkg/old.py": None, "src/pkg/new.py": legacy + "extra = 1\n"}

    assert _comment_kinds(repo, before, after) == 0


def test_comment_kinds_without_base_exits_2() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["comment-kinds"])

    assert exit_info.value.code == 2


def _why_not(repo: Path, source: str) -> int:
    """Add `source` after one line of code and run comment-kinds over that change."""
    return _comment_kinds(repo, {"src/pkg/load.py": "x = 1\n"}, {"src/pkg/load.py": source})


def test_why_not_fails_when_its_name_is_missing_from_the_next_logical_line(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    source = (
        "x = 1\n# WHY-NOT(retries): the upstream rate limit resets every minute.\ntimeout = 30\n"
    )

    assert _why_not(repo, source) == 1
    err = capsys.readouterr().err
    assert "src/pkg/load.py:2: " in err
    assert "'retries'" in err
    assert "next logical line (line 3)" in err


def test_why_not_fails_when_its_name_appears_only_on_a_later_line(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    source = (
        "x = 1\n"
        "# WHY-NOT(retries): the upstream rate limit resets every minute.\n"
        "timeout = 30\n"
        "retries = 3\n"
    )

    assert _why_not(repo, source) == 1
    assert "next logical line (line 3)" in capsys.readouterr().err


def test_why_not_matches_a_name_anywhere_in_a_multi_line_statement(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    source = (
        "x = 1\n"
        "# WHY-NOT(retries): the upstream rate limit resets every minute.\n"
        "client = connect(\n"
        "    host,\n"
        "    retries=3,\n"
        ")\n"
    )

    assert _why_not(repo, source) == 0


def test_why_not_inside_a_call_matches_the_rest_of_that_statement(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    source = (
        "x = 1\n"
        "client = connect(\n"
        "    retries=3,\n"
        "    # WHY-NOT(host): the proxy pins one upstream.\n"
        "    host=HOST,\n"
        "    # WHY-NOT(retries): named only above this block.\n"
        "    timeout=30,\n"
        ")\n"
    )

    assert _why_not(repo, source) == 1
    err = capsys.readouterr().err
    assert "src/pkg/load.py:6: " in err
    assert "src/pkg/load.py:4: " not in err


def test_why_not_matches_a_function_name_on_its_def_line(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    source = (
        "x = 1\n"
        "# WHY-NOT(load_rows): rows stay lazy because the cache is larger than memory.\n"
        "def load_rows(limit):\n"
        "    return limit\n"
    )

    assert _why_not(repo, source) == 0


def test_why_not_matches_a_parameter_name_inside_a_decorator(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    source = (
        "x = 1\n"
        "# WHY-NOT(retry_policy): 重試間隔加總必須小於 10 分鐘 slot，否則會和下一輪排程重疊\n"
        "@asset(\n"
        "    description='Rows.',\n"
        "    retry_policy=RetryPolicy(max_retries=2),\n"
        ")\n"
        "def rows():\n"
        "    return 1\n"
    )

    assert _why_not(repo, source) == 0


def test_why_not_matches_the_last_part_of_a_dotted_name(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    matching = "x = 1\n# WHY-NOT(Settings.max_wait): slots are ten minutes.\nself.max_wait = 5\n"
    assert _why_not(repo, matching) == 0

    missing = "x = 1\n# WHY-NOT(max_wait.Settings): slots are ten minutes.\nself.max_wait = 5\n"
    assert _why_not(repo, missing) == 1
    assert "'Settings' (from 'max_wait.Settings')" in capsys.readouterr().err


def test_why_not_trailing_comment_must_name_code_on_its_own_logical_line(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    source = (
        "x = 1\n"
        "timeout = 30  # WHY-NOT(retries): the upstream rate limit resets every minute.\n"
        "retries = 3\n"
    )

    assert _why_not(repo, source) == 1
    err = capsys.readouterr().err
    assert "src/pkg/load.py:2: " in err
    assert "'retries' must appear on the same logical line (line 2)" in err


def test_why_not_trailing_comment_inside_a_multi_line_statement_passes(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    source = (
        "x = 1\n"
        "client = connect(\n"
        "    host,  # WHY-NOT(retries): the upstream rate limit resets every minute.\n"
        "    retries=3,\n"
        ")\n"
    )

    assert _why_not(repo, source) == 0


def test_why_not_fails_when_no_code_follows_the_block(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_conventions, "REPO_ROOT", repo)
    source = "x = 1\n# WHY-NOT(retries): the upstream rate limit resets every minute.\n"

    assert _why_not(repo, source) == 1
    assert "no code follows the comment" in capsys.readouterr().err
