"""Offline tests for the repository convention checks in scripts/check_conventions.py."""

from datetime import date
from pathlib import Path

from check_conventions import (
    Violation,
    check_docker_pins,
    doc_date_violation,
    find_banned_terms,
    find_host_python_in_makefile,
    find_host_python_in_workflow,
    find_last_updated,
    find_unlinked_debt_markers,
    find_unpinned_pip_installs,
    is_debt_marker_source,
    python_comments,
)


def _lines(commands) -> list[int]:
    return [command.line for command in commands]


def test_makefile_recipe_starting_with_python3_is_flagged() -> None:
    makefile = "frontend-smoke:\n\tpython3 scripts/smoke_nginx.py $(ARGS)\n"

    flagged = find_host_python_in_makefile(makefile)

    assert _lines(flagged) == [2]


def test_makefile_recipe_running_python_through_uv_is_allowed() -> None:
    makefile = "frontend-smoke:\n\tuv run --no-project python scripts/smoke_nginx.py $(ARGS)\n"

    assert find_host_python_in_makefile(makefile) == []


def test_makefile_python_on_continuation_of_container_exec_is_allowed() -> None:
    makefile = (
        "smoke-check:\n"
        "\tdocker compose -f docker/docker-compose.yml exec dagster-webserver \\\n"
        "\t\tpython -m shiro_mlops.pipelines.smoke_check $(ARGS)\n"
    )

    assert find_host_python_in_makefile(makefile) == []


def test_makefile_silent_recipe_prefix_does_not_hide_python() -> None:
    makefile = "report:\n\t@python scripts/report.py\n"

    flagged = find_host_python_in_makefile(makefile)

    assert _lines(flagged) == [2]


def test_python_after_shell_separator_is_flagged() -> None:
    makefile = "build:\n\tcd frontend && python3 -m http.server\n"

    flagged = find_host_python_in_makefile(makefile)

    assert _lines(flagged) == [2]


def test_python_after_environment_assignment_is_flagged() -> None:
    makefile = "train:\n\tDATA_DIR=data python train.py\n"

    flagged = find_host_python_in_makefile(makefile)

    assert _lines(flagged) == [2]


def test_python_inside_quoted_argument_is_allowed() -> None:
    makefile = 'hint:\n\techo "python3 is not used directly"\n'

    assert find_host_python_in_makefile(makefile) == []


def test_workflow_block_reports_line_of_host_python() -> None:
    workflow = (
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - name: Run\n"
        "        run: |\n"
        "          uv sync --all-extras\n"
        "          python3 scripts/smoke_nginx.py\n"
        "      - name: Set up Python\n"
        "        uses: actions/setup-python@v5\n"
    )

    flagged = find_host_python_in_workflow(workflow)

    assert _lines(flagged) == [7]


def test_workflow_python_as_argument_of_docker_run_is_allowed() -> None:
    workflow = (
        "      - run: |\n"
        "          start_stub_api() {\n"
        '            docker run -d --name "$1" --network-alias api \\\n'
        "              python:3.11-alpine python /stub_api.py\n"
        "          }\n"
    )

    assert find_host_python_in_workflow(workflow) == []


def test_workflow_inline_run_starting_with_python_is_flagged() -> None:
    workflow = "    steps:\n      - run: python -m pytest\n"

    flagged = find_host_python_in_workflow(workflow)

    assert _lines(flagged) == [2]


def test_workflow_defaults_run_mapping_is_not_a_command() -> None:
    workflow = "    defaults:\n      run:\n        working-directory: frontend\n"

    assert find_host_python_in_workflow(workflow) == []


def test_workflow_folded_block_is_one_command() -> None:
    workflow = "      - run: >\n          docker run --rm image\n          python /app.py\n"

    assert find_host_python_in_workflow(workflow) == []


def test_banned_term_reports_line_and_preferred_replacement() -> None:
    markdown = "# Title\n\n服務端口如下\n"

    hits = find_banned_terms(markdown)

    assert [(hit.line, hit.term, hit.replacement) for hit in hits] == [(3, "端口", "連接埠")]


def test_preferred_term_is_not_reported() -> None:
    assert find_banned_terms("服務連接埠如下\n") == []


def test_last_updated_header_in_list_item_is_found() -> None:
    markdown = "# Doc\n\n- 建立日期：2026-08-25\n- 最後更新：2026-08-26\n"

    header = find_last_updated(markdown)

    assert (header.line, header.value) == (4, date(2026, 8, 26))


def test_last_updated_header_in_blockquote_is_found() -> None:
    markdown = "# Doc\n\n> 最後更新：2026-09-27\n"

    header = find_last_updated(markdown)

    assert (header.line, header.value) == (3, date(2026, 9, 27))


def test_english_last_updated_header_is_found() -> None:
    markdown = "# ADR\n\n> - Created: 2026-09-07\n> - Last Updated: 2026-09-08\n"

    header = find_last_updated(markdown)

    assert header.value == date(2026, 9, 8)


def test_first_last_updated_line_is_the_header() -> None:
    markdown = "- 最後更新：2026-09-07\n\n## Notes\n\n- 最後更新：2026-09-04（補充說明）。\n"

    header = find_last_updated(markdown)

    assert header.line == 1


def test_document_without_last_updated_header_has_none() -> None:
    assert find_last_updated("# Changelog\n\n## [Unreleased]\n") is None


def test_header_older_than_change_is_a_violation() -> None:
    markdown = "# Doc\n\n- 最後更新：2026-08-26\n"

    violation = doc_date_violation("docs/doc.md", markdown, changed_on=date(2026, 10, 25))

    assert (violation.path, violation.line) == ("docs/doc.md", 3)


def test_header_already_on_change_date_passes() -> None:
    markdown = "# Doc\n\n- 最後更新：2026-10-25\n"

    assert doc_date_violation("docs/doc.md", markdown, changed_on=date(2026, 10, 25)) is None


def test_document_without_header_is_a_violation_on_its_first_line() -> None:
    violation = doc_date_violation("CHANGELOG.md", "# Changelog\n", changed_on=date(2026, 10, 25))

    assert (violation.path, violation.line) == ("CHANGELOG.md", 1)


def test_invalid_header_date_is_a_violation() -> None:
    markdown = "- 最後更新：2026-13-01\n"

    violation = doc_date_violation("docs/doc.md", markdown, changed_on=date(2026, 10, 25))

    assert violation.line == 1


def test_lab_markdown_without_header_is_excluded_from_doc_dates() -> None:
    violation = doc_date_violation(
        "lab/2026-11-08-dhf-hyperparameter-search/README.md",
        "# Research Report\n",
        changed_on=date(2026, 11, 8),
    )

    assert violation is None


def test_debt_marker_without_issue_reference_is_flagged() -> None:
    source = "def load():\n    # TODO: retry on timeout\n    return None\n"

    hits = find_unlinked_debt_markers(source)

    assert [(hit.line, hit.text) for hit in hits] == [(2, "TODO")]


def test_debt_marker_with_issue_reference_is_allowed() -> None:
    source = "# TODO(#123): retry on timeout\n// FIXME(#7) clamp horizon\n"

    assert find_unlinked_debt_markers(source) == []


def test_every_debt_marker_kind_is_checked() -> None:
    source = "# FIXME later\n# HACK around upstream\n# XXX unclear\n"

    hits = find_unlinked_debt_markers(source)

    assert [hit.text for hit in hits] == ["FIXME", "HACK", "XXX"]


def test_marker_inside_a_longer_word_is_not_a_debt_marker() -> None:
    assert find_unlinked_debt_markers("todo_items = TODOS + MY_TODO_LIST\n") == []


def test_issue_reference_must_follow_the_marker_directly() -> None:
    hits = find_unlinked_debt_markers("# TODO see (#123)\n")

    assert [hit.line for hit in hits] == [1]


def test_source_files_are_scanned_for_debt_markers() -> None:
    scanned = [
        "src/shiro_mlops/service/api.py",
        "frontend/src/routes/index.tsx",
        "docker/Dockerfile.api",
        "Makefile",
        ".github/workflows/ci.yml",
    ]

    assert all(is_debt_marker_source(path) for path in scanned)


def test_docs_data_and_the_checker_itself_are_not_scanned_for_debt_markers() -> None:
    skipped = [
        "docs/agents/tech-debt.md",
        "tests/fixtures/taipower_load.json",
        "uv.lock",
        "scripts/check_conventions.py",
        "tests/unit/test_check_conventions.py",
        "tests/integration/test_check_conventions_git.py",
        "frontend/node_modules/pkg/index.js",
    ]

    assert not any(is_debt_marker_source(path) for path in skipped)


def test_comments_are_full_line_only_when_nothing_but_indentation_precedes_them() -> None:
    source = (
        "# header\n"
        "def load():\n"
        "    # indented\n"
        '    text = """first\n'
        'last"""  # after a multi-line string\n'
        "    return text  # trailing\n"
    )

    comments = python_comments(source)

    assert [(comment.line, comment.full_line) for comment in comments] == [
        (1, True),
        (3, True),
        (5, False),
        (6, False),
    ]


def _unpinned(dockerfile: str) -> list[tuple[int, list[str]]]:
    return [(hit.line, list(hit.packages)) for hit in find_unpinned_pip_installs(dockerfile)]


def test_dockerfile_pip_install_without_versions_reports_line_and_packages() -> None:
    dockerfile = "FROM python:3.11-slim\n\nRUN pip install --no-cache-dir mlflow psycopg2-binary\n"

    assert _unpinned(dockerfile) == [(3, ["mlflow", "psycopg2-binary"])]


def test_pip_install_chained_on_a_continued_run_line_is_reported_at_the_run_line() -> None:
    dockerfile = (
        "FROM python:3.11-slim\n"
        "RUN apt-get update \\\n"
        "    && pip install --no-cache-dir mlflow \\\n"
        "    && rm -rf /var/lib/apt/lists/*\n"
    )

    assert _unpinned(dockerfile) == [(2, ["mlflow"])]


def test_every_pip_installer_spelling_is_checked() -> None:
    dockerfile = (
        "RUN uv pip install --system fastapi\n"
        "RUN pip3 install uvicorn\n"
        "RUN python -m pip install --upgrade pip\n"
        "RUN /usr/local/bin/python3.11 -m pip install lightgbm\n"
    )

    assert _unpinned(dockerfile) == [
        (1, ["fastapi"]),
        (2, ["uvicorn"]),
        (3, ["pip"]),
        (4, ["lightgbm"]),
    ]


def test_pinned_lock_file_and_local_project_installs_are_allowed() -> None:
    dockerfile = (
        "RUN pip install mlflow==3.18.0 'psycopg[binary]==3.2.3'\n"
        "RUN uv pip install --system --no-cache -r /tmp/requirements.txt\n"
        "RUN uv pip install --system --no-cache --no-deps -e .\n"
        "RUN pip install --index-url https://pypi.example/simple --requirement requirements.lock\n"
    )

    assert _unpinned(dockerfile) == []


def test_docker_pins_reports_each_unpinned_dockerfile_under_docker(tmp_path: Path) -> None:
    docker = tmp_path / "docker"
    docker.mkdir()
    (docker / "Dockerfile.api").write_text("RUN uv pip install --system -r /tmp/req.txt\n")
    (docker / "Dockerfile.mlflow").write_text(
        "FROM python:3.11-slim\n\nRUN pip install --no-cache-dir mlflow psycopg2-binary\n"
    )

    assert check_docker_pins(tmp_path) == [
        Violation(
            "docker/Dockerfile.mlflow",
            3,
            "pin pip installs with ==, or install under a lock file with -c or -r: mlflow, psycopg2-binary",
        )
    ]


def test_pip_install_behind_run_flags_env_assignments_and_shell_keywords_is_checked() -> None:
    dockerfile = (
        "RUN --mount=type=cache,target=/root/.cache pip install mlflow\n"
        "RUN PIP_NO_CACHE_DIR=1 pip install fastapi\n"
        "RUN if true; then pip install uvicorn; fi\n"
    )

    assert _unpinned(dockerfile) == [(1, ["mlflow"]), (2, ["fastapi"]), (3, ["uvicorn"])]


def test_installer_options_before_the_install_subcommand_do_not_hide_it() -> None:
    dockerfile = (
        "RUN uv --no-cache pip install fastapi\n"
        "RUN pip -q install uvicorn\n"
        "RUN python -u -m pip install lightgbm\n"
    )

    assert _unpinned(dockerfile) == [(1, ["fastapi"]), (2, ["uvicorn"]), (3, ["lightgbm"])]


def test_double_equals_outside_an_exact_version_is_not_a_pin() -> None:
    dockerfile = (
        "RUN pip install 'mlflow>=3,==3.15.1'\n"
        "RUN pip install 'fastapi; python_version==\"3.11\"'\n"
        "RUN pip install lightgbm==4.*\n"
    )

    assert _unpinned(dockerfile) == [
        (1, ["mlflow>=3,==3.15.1"]),
        (2, ['fastapi; python_version=="3.11"']),
        (3, ["lightgbm==4.*"]),
    ]


def test_shell_redirections_after_pinned_packages_are_not_packages() -> None:
    dockerfile = (
        "RUN pip install mlflow==3.15.1 > /dev/null 2>&1\nRUN pip install x==1 2>/dev/null\n"
    )

    assert _unpinned(dockerfile) == []


def test_packages_installed_under_a_constraints_file_are_pinned_by_it() -> None:
    dockerfile = (
        "RUN uv pip install --system --no-cache -c /tmp/constraints.txt mlflow psycopg2-binary\n"
        "RUN pip install --constraint=constraints.txt fastapi\n"
        "RUN pip install -cconstraints.txt uvicorn\n"
    )

    assert _unpinned(dockerfile) == []
