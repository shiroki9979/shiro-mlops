"""Offline tests for the repository convention checks in scripts/check_conventions.py."""

from datetime import date

from check_conventions import (
    doc_date_violation,
    find_banned_terms,
    find_host_python_in_makefile,
    find_host_python_in_workflow,
    find_last_updated,
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
