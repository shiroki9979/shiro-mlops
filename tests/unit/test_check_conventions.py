"""Offline tests for the repository convention checks in scripts/check_conventions.py."""

from datetime import date
from pathlib import Path

import pytest
from check_conventions import (
    Violation,
    check_action_pins,
    check_docker_pins,
    check_pin_sync,
    check_python_uv,
    doc_date_violation,
    doc_metadata_violations,
    find_banned_terms,
    find_host_python_in_makefile,
    find_host_python_in_workflow,
    find_last_updated,
    find_unlinked_debt_markers,
    find_unpinned_actions,
    find_unpinned_compose_images,
    find_unpinned_images,
    find_unpinned_pip_installs,
    find_unpinned_uv_setups,
    is_debt_marker_source,
    is_terms_exempt_path,
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


def test_banned_term_on_a_glossary_avoid_line_is_not_reported() -> None:
    markdown = "- **連接埠 (Port)**：服務監聽的埠號。\n  _Avoid_：端口（舊稱）。\n"

    assert find_banned_terms(markdown) == []


def test_banned_term_outside_the_avoid_line_of_the_same_file_is_still_reported() -> None:
    markdown = "- **連接埠 (Port)**：服務端口。\n  _Avoid_：端口（舊稱）。\n"

    assert [hit.line for hit in find_banned_terms(markdown)] == [1]


def test_avoid_marker_after_other_text_does_not_exempt_the_line() -> None:
    assert [hit.line for hit in find_banned_terms("服務端口，見 _Avoid_：。\n")] == [1]


@pytest.mark.parametrize(
    ("path", "exempt"),
    [
        ("docs/research/2026-11-27-ml-governance-terminology.md", True),
        ("docs/research/sub/notes.md", True),
        ("docs/reference/data-contracts.md", False),
        ("GLOSSARY.md", False),
        ("lab/docs/research/notes.md", False),
    ],
)
def test_only_markdown_under_docs_research_is_exempt_from_terms(path: str, exempt: bool) -> None:
    assert is_terms_exempt_path(path) is exempt


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


@pytest.mark.parametrize(
    "path", ["data/raw/notes.md", "frontend/node_modules/pkg/README.md", ".venv/lib/README.md"]
)
def test_markdown_that_markdownlint_ignores_is_excluded_from_doc_dates(path: str) -> None:
    assert doc_date_violation(path, "# Notes\n", changed_on=date(2026, 11, 8)) is None


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
        f"FROM python:3.11-slim{DIGEST}\n\nRUN pip install --no-cache-dir mlflow psycopg2-binary\n"
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


# --- shell forms that used to hide a host python or an unpinned install --------------------


def test_workflow_run_with_the_command_on_the_next_line_is_checked() -> None:
    """A plain YAML scalar may start on the line after `run:`."""
    workflow = "    steps:\n      - run:\n          python3 scripts/smoke_nginx.py\n"

    assert _lines(find_host_python_in_workflow(workflow)) == [3]


def test_workflow_run_on_the_next_line_still_ends_at_the_next_key() -> None:
    workflow = "      - run:\n          uv run pytest\n        env:\n          PYTHON: python3\n"

    assert find_host_python_in_workflow(workflow) == []


@pytest.mark.parametrize(
    "command",
    [
        'echo "version=$(python3 -c "import sys; print(sys.version)")"',
        "echo `python3 --version`",
        'VALUE="`python -c 1`"',
        "sudo python3 setup.py",
        "env PYTHONPATH=src python -m pytest",
        "exec python3 app.py",
        "command python3 app.py",
        "nohup python3 worker.py &",
        'case "$1" in smoke) python3 scripts/smoke_nginx.py ;; esac',
        "bash -c 'python3 scripts/smoke_nginx.py'",
        'sh -ec "cd frontend && python3 -m http.server"',
    ],
)
def test_host_python_behind_substitutions_wrappers_and_nested_shells_is_flagged(
    command: str,
) -> None:
    assert _lines(find_host_python_in_makefile(f"target:\n\t{command}\n")) == [2]


@pytest.mark.parametrize(
    "command",
    [
        'echo "python3 is not used directly"',
        "echo 'run $(python3 -V) yourself'",
        "uv run python -m pytest",
        "sudo -u runner uv run python app.py",
        "env -u PYTHONPATH uv run python app.py",
        "bash -c 'uv run python scripts/smoke_nginx.py'",
    ],
)
def test_python_through_uv_or_as_plain_text_stays_allowed(command: str) -> None:
    assert find_host_python_in_makefile(f"target:\n\t{command}\n") == []


def test_python_uv_reads_workflows_with_either_yaml_extension(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (tmp_path / "Makefile").write_text("", encoding="utf-8")
    (workflows / "ci.yml").write_text("      - run: python3 a.py\n", encoding="utf-8")
    (workflows / "release.yaml").write_text("      - run: python3 b.py\n", encoding="utf-8")

    assert sorted(violation.path for violation in check_python_uv(tmp_path)) == [
        ".github/workflows/ci.yml",
        ".github/workflows/release.yaml",
    ]


@pytest.mark.parametrize(
    "dockerfile",
    [
        pytest.param("RUN <<EOF\npip install requests\nEOF\n", id="heredoc"),
        pytest.param(
            "RUN --mount=type=cache,target=/root/.cache <<EOT\nset -e\npip install requests\nEOT\n",
            id="heredoc-after-run-flags",
        ),
        pytest.param("RUN <<-'EOF'\n\tpip install requests\n\tEOF\n", id="indented-quoted-heredoc"),
        pytest.param('RUN ["pip", "install", "requests"]\n', id="exec-form"),
        pytest.param('RUN ["/bin/sh", "-c", "pip install requests"]\n', id="exec-form-shell"),
        pytest.param('RUN sh -c "pip install requests"\n', id="sh-c"),
        pytest.param("RUN bash -lc 'pip install requests'\n", id="bash-lc"),
        pytest.param("RUN env PIP_NO_CACHE_DIR=1 pip install requests\n", id="env"),
        pytest.param("RUN sudo -H pip install requests\n", id="sudo"),
        pytest.param("RUN pip --cache-dir /tmp/c install requests\n", id="option-value-first"),
        pytest.param("ONBUILD RUN pip install requests\n", id="onbuild"),
    ],
)
def test_unpinned_installs_behind_every_run_spelling_are_reported(dockerfile: str) -> None:
    assert _unpinned(dockerfile) == [(1, ["requests"])]


def test_a_heredoc_body_is_not_read_as_dockerfile_instructions() -> None:
    dockerfile = (
        "RUN <<EOF\n"
        "pip install requests==2.32.3\n"
        "echo RUN pip install loose\n"
        "EOF\n"
        "RUN pip install fastapi\n"
    )

    assert _unpinned(dockerfile) == [(5, ["fastapi"])]


def test_pinned_installs_behind_wrappers_stay_allowed() -> None:
    dockerfile = (
        'RUN sh -c "pip install requests==2.32.3"\n'
        'RUN ["pip", "install", "-r", "/tmp/requirements.txt"]\n'
        "RUN <<EOF\nuv pip install --system -c /tmp/constraints.txt mlflow\nEOF\n"
    )

    assert _unpinned(dockerfile) == []


CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"


def test_actions_referenced_by_tag_branch_or_short_sha_are_reported() -> None:
    workflow = (
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - name: Install uv\n"
        "        uses: 'astral-sh/setup-uv@main'\n"
        '      - uses: "aws-actions/configure-aws-credentials@11bd719"  # v4\n'
    )

    assert [(hit.line, hit.text) for hit in find_unpinned_actions(workflow)] == [
        (2, "actions/checkout@v4"),
        (4, "astral-sh/setup-uv@main"),
        (5, "aws-actions/configure-aws-credentials@11bd719"),
    ]


def test_actions_at_a_full_commit_sha_local_actions_and_docker_digests_are_allowed() -> None:
    workflow = (
        f"      - uses: actions/checkout@{CHECKOUT_SHA} # v4.2.2\n"
        f"        uses: github/codeql-action/init@{CHECKOUT_SHA}\n"
        "      - uses: ./.github/actions/setup\n"
        "      - uses: docker://alpine:3.20@sha256:" + "a" * 64 + "\n"
        "      - run: echo uses: actions/checkout@v4\n"
    )

    assert find_unpinned_actions(workflow) == []


def test_setup_uv_without_an_exact_uv_version_is_reported_at_its_version_or_uses_line() -> None:
    workflow = (
        "    steps:\n"
        "      - name: Install uv\n"
        f"        uses: astral-sh/setup-uv@{CHECKOUT_SHA} # v2\n"
        "        with:\n"
        '          version: "latest"\n'
        "          enable-cache: true\n"
        f"      - uses: astral-sh/setup-uv@{CHECKOUT_SHA}\n"
        "      - name: Uses with before\n"
        "        with:\n"
        "          version: 0.11\n"
        f"        uses: astral-sh/setup-uv@{CHECKOUT_SHA}\n"
    )

    assert [(hit.line, hit.text) for hit in find_unpinned_uv_setups(workflow)] == [
        (5, "latest"),
        (7, ""),
        (10, "0.11"),
    ]


def test_setup_uv_with_an_exact_version_and_other_steps_versions_are_allowed() -> None:
    workflow = (
        "      - name: Install uv\n"
        f"        uses: astral-sh/setup-uv@{CHECKOUT_SHA} # v2\n"
        "        with:\n"
        "          version: '0.11.32'  # matches docker/Dockerfile.*\n"
        "      - uses: actions/setup-python@v5\n"
        "        with:\n"
        "          version: latest\n"
    )

    assert find_unpinned_uv_setups(workflow) == []


DIGEST = "@sha256:" + "b" * 64


def _images(dockerfile: str) -> list[tuple[int, str]]:
    return [(hit.line, hit.text) for hit in find_unpinned_images(dockerfile)]


def test_base_and_copied_images_without_a_digest_are_reported() -> None:
    dockerfile = (
        "ARG NODE_VERSION=24.19.0\n"
        "FROM node:${NODE_VERSION}-alpine AS build\n"
        "COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /bin/uv\n"
        "from --platform=$BUILDPLATFORM python:3.11-slim\n"
        "FROM nginx:1.30-alpine\n"
    )

    assert _images(dockerfile) == [
        (2, "node:${NODE_VERSION}-alpine"),
        (3, "ghcr.io/astral-sh/uv:0.11.32"),
        (4, "python:3.11-slim"),
        (5, "nginx:1.30-alpine"),
    ]


def test_images_with_a_digest_stage_names_and_scratch_are_allowed() -> None:
    dockerfile = (
        f"FROM node:24.19.0-alpine{DIGEST} AS Build\n"
        f"COPY --from=ghcr.io/astral-sh/uv:0.11.32{DIGEST} /uv /bin/uv\n"
        "FROM build AS test\n"
        "FROM scratch\n"
        "COPY --from=build /app/dist /usr/share/nginx/html\n"
        "COPY --from=0 /app /app\n"
        "# FROM python:3.11-slim\n"
    )

    assert _images(dockerfile) == []


def test_compose_images_without_a_digest_are_reported() -> None:
    compose = (
        "services:\n"
        "  postgres:\n"
        "    image: timescale/timescaledb:latest-pg15\n"
        "  redis:\n"
        '    image: "redis:7-alpine"  # cache\n'
        "  pinned:\n"
        f"    image: redis:7.4.2-alpine{DIGEST}\n"
        "  api:\n"
        "    build:\n"
        "      context: ..\n"
        "    environment:\n"
        "      DOCS: 'image: not-a-key'\n"
    )

    assert [(hit.line, hit.text) for hit in find_unpinned_compose_images(compose)] == [
        (3, "timescale/timescaledb:latest-pg15"),
        (5, "redis:7-alpine"),
    ]


def test_docker_pins_reads_backend_and_frontend_dockerfiles_and_compose(tmp_path: Path) -> None:
    (tmp_path / "docker").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "docker" / "Dockerfile.api").write_text(f"FROM python:3.11-slim{DIGEST}\n")
    (tmp_path / "docker" / "docker-compose.yml").write_text(
        "services:\n  redis:\n    image: redis:7-alpine\n"
    )
    (tmp_path / "frontend" / "Dockerfile").write_text(
        f"FROM node:24-alpine{DIGEST} AS build\nFROM nginx:1.30-alpine\n"
    )

    assert check_docker_pins(tmp_path) == [
        Violation(
            "docker/docker-compose.yml",
            3,
            "pin images to a digest, as in name:tag@sha256:<digest>: redis:7-alpine",
        ),
        Violation(
            "frontend/Dockerfile",
            2,
            "pin images to a digest, as in name:tag@sha256:<digest>: nginx:1.30-alpine",
        ),
    ]


def test_action_pins_reports_unpinned_actions_and_uv_versions_in_every_workflow(
    tmp_path: Path,
) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        f"      - uses: astral-sh/setup-uv@{CHECKOUT_SHA} # v2\n"
        "        with:\n"
        "          version: latest\n"
    )
    (workflows / "release.yaml").write_text(f"      - uses: actions/checkout@{CHECKOUT_SHA}\n")

    assert check_action_pins(tmp_path) == [
        Violation(
            ".github/workflows/ci.yml",
            2,
            "pin actions to a full commit SHA, with the release as a comment: actions/checkout@v4",
        ),
        Violation(
            ".github/workflows/ci.yml",
            5,
            "set setup-uv `with: version:` to an exact uv release (X.Y.Z), not: latest",
        ),
    ]


def test_setup_uv_version_from_workflow_env_is_resolved() -> None:
    workflow = (
        "env:\n"
        '  UV_VERSION: "0.11.32"\n'
        "  LOOSE_UV: latest\n"
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        f"      - uses: astral-sh/setup-uv@{CHECKOUT_SHA}\n"
        "        with:\n"
        "          version: ${{ env.UV_VERSION }}\n"
        f"      - uses: astral-sh/setup-uv@{CHECKOUT_SHA}\n"
        "        with:\n"
        "          version: ${{ env.LOOSE_UV }}\n"
    )

    assert [(hit.line, hit.text) for hit in find_unpinned_uv_setups(workflow)] == [
        (12, "${{ env.LOOSE_UV }}"),
    ]


def test_setup_uv_version_is_found_across_blank_lines_but_not_inside_a_block_scalar() -> None:
    workflow = (
        "      - name: Version before uses\n"
        "        with:\n"
        '          version: "0.11.32"\n'
        "\n"
        "        # setup\n"
        f"        uses: astral-sh/setup-uv@{CHECKOUT_SHA}\n"
        f"      - uses: astral-sh/setup-uv@{CHECKOUT_SHA}\n"
        "        with:\n"
        "          cache-dependency-glob: |\n"
        "            version: 0.11.32\n"
    )

    assert [(hit.line, hit.text) for hit in find_unpinned_uv_setups(workflow)] == [(7, "")]


def test_uses_lines_inside_a_run_script_are_not_actions() -> None:
    workflow = "      - run: |\n          echo done\n          uses: actions/checkout@v4\n"

    assert find_unpinned_actions(workflow) == []


def test_quoted_stage_names_are_stages_and_a_digest_needs_a_tag() -> None:
    dockerfile = (
        f'FROM node:24-alpine{DIGEST} AS build\nCOPY --from="build" /app /app\nFROM nginx{DIGEST}\n'
    )

    assert _images(dockerfile) == [(3, f"nginx{DIGEST}")]


def _pinned_repo(
    tmp_path: Path,
    *,
    uv_env: str = "0.11.32",
    uv_image: str = "0.11.32",
    compose_db: str = "2.28.3-pg15",
    script_db: str = "2.28.3-pg15",
    lock_versions: tuple[str, str] = ("5.100.0", "5.100.0"),
) -> Path:
    """A repo with every copy of a version that pin-sync compares, each set as given."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "env:\n"
        f'  UV_VERSION: "{uv_env}"\n'
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        f"      - uses: astral-sh/setup-uv@{CHECKOUT_SHA} # v2\n"
        "        with:\n"
        "          version: ${{ env.UV_VERSION }}\n"
    )
    docker = tmp_path / "docker"
    docker.mkdir()
    (docker / "Dockerfile.api").write_text(
        f"FROM python:3.11-slim{DIGEST}\n"
        f"COPY --from=ghcr.io/astral-sh/uv:{uv_image}{DIGEST} /uv /bin/uv\n"
    )
    (docker / "docker-compose.yml").write_text(
        f"services:\n  postgres:\n    image: timescale/timescaledb:{compose_db}{DIGEST}\n"
    )
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "acceptance.sh").write_text(
        "#!/usr/bin/env bash\n"
        "docker run --rm \\\n"
        f"  timescale/timescaledb:{script_db}{DIGEST} >/dev/null\n"
        f'readonly STUB_IMAGE="python:3.11.18-alpine{DIGEST}"\n'
    )
    for layer, version in zip((".", "bootstrap"), lock_versions, strict=True):
        directory = tmp_path / "infra" / "terraform" / layer
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".terraform.lock.hcl").write_text(
            'provider "registry.terraform.io/hashicorp/aws" {\n'
            f'  version     = "{version}"\n'
            '  constraints = "~> 5.0"\n'
            "}\n"
        )
    return tmp_path


def test_pin_sync_passes_when_every_copy_agrees(tmp_path: Path) -> None:
    assert check_pin_sync(_pinned_repo(tmp_path)) == []


def test_pin_sync_reports_each_uv_copy_when_the_workflow_and_a_dockerfile_disagree(
    tmp_path: Path,
) -> None:
    repo = _pinned_repo(tmp_path, uv_image="0.11.33")

    assert check_pin_sync(repo) == [
        Violation(
            ".github/workflows/ci.yml",
            8,
            "uv pins disagree: 0.11.32 here, 0.11.33 at docker/Dockerfile.api:2; "
            "update every copy together",
        ),
        Violation(
            "docker/Dockerfile.api",
            2,
            "uv pins disagree: 0.11.33 here, 0.11.32 at .github/workflows/ci.yml:8; "
            "update every copy together",
        ),
    ]


def test_pin_sync_reports_a_script_image_that_differs_from_the_compose_image(
    tmp_path: Path,
) -> None:
    repo = _pinned_repo(tmp_path, compose_db="2.28.4-pg15")

    assert [(violation.path, violation.line) for violation in check_pin_sync(repo)] == [
        ("docker/docker-compose.yml", 3),
        ("scripts/acceptance.sh", 3),
    ]
    assert check_pin_sync(repo)[1].message == (
        f"image timescale/timescaledb pins disagree: 2.28.3-pg15{DIGEST} here, "
        f"2.28.4-pg15{DIGEST} at docker/docker-compose.yml:3; update every copy together"
    )


def test_pin_sync_reports_a_provider_locked_to_different_versions_in_two_layers(
    tmp_path: Path,
) -> None:
    repo = _pinned_repo(tmp_path, lock_versions=("5.100.0", "5.101.0"))

    assert check_pin_sync(repo) == [
        Violation(
            "infra/terraform/.terraform.lock.hcl",
            2,
            "provider registry.terraform.io/hashicorp/aws pins disagree: 5.100.0 here, "
            "5.101.0 at infra/terraform/bootstrap/.terraform.lock.hcl:2; "
            "update every copy together",
        ),
        Violation(
            "infra/terraform/bootstrap/.terraform.lock.hcl",
            2,
            "provider registry.terraform.io/hashicorp/aws pins disagree: 5.101.0 here, "
            "5.100.0 at infra/terraform/.terraform.lock.hcl:2; update every copy together",
        ),
    ]


def test_pin_sync_compares_uv_image_variants_by_release_and_leaves_loose_pins_to_action_pins(
    tmp_path: Path,
) -> None:
    repo = _pinned_repo(tmp_path, uv_env="latest", uv_image="0.11.32-python3.11-bookworm")
    (repo / "docker" / "Dockerfile.dagster").write_text(
        f"COPY --from=ghcr.io/astral-sh/uv:0.11.32{DIGEST} /uv /bin/uv\n"
    )

    assert check_pin_sync(repo) == []


ADR_PATH = "docs/adr/0001-title.md"
DOC_PATH = "docs/reference/guide.md"


def _adr_doc(metadata: str = "", body: str = "## 1. Context\n\nBody.\n") -> str:
    block = metadata or (
        "> - Created: 2026-10-01\n> - Last Updated: 2026-10-02\n> - Status: Accepted\n"
    )
    return f"# ADR-0001：Title\n\n{block}\n---\n\n{body}"


def _general_doc(metadata: str = "", intro: str = "", body: str = "## 1. Scope\n\nBody.\n") -> str:
    block = metadata or "> - Created: 2026-10-01\n> - Last Updated: 2026-10-02\n"
    return f"# Guide\n\n{block}\n{intro}{body}"


def _metadata_hits(path: str, markdown: str | bytes) -> list[tuple[str, int, str]]:
    """Each violation as (path, line, rule code), the code being the message's first word."""
    return [
        (violation.path, violation.line, violation.message.split(":", 1)[0])
        for violation in doc_metadata_violations(path, markdown)
    ]


def test_conforming_adr_and_general_doc_have_no_metadata_violations() -> None:
    assert _metadata_hits(ADR_PATH, _adr_doc()) == []
    assert _metadata_hits(DOC_PATH, _general_doc()) == []


def test_doc_whose_first_line_is_not_an_h1_is_a_violation() -> None:
    markdown = "<!-- markdownlint-disable MD024 -->\n" + _general_doc()

    assert _metadata_hits(DOC_PATH, markdown) == [(DOC_PATH, 1, "h1-first-line")]


def test_doc_that_is_not_utf8_is_reported_at_the_undecodable_line() -> None:
    markdown = b"# Guide\n\n" + "最後更新\n".encode("big5")

    assert _metadata_hits(DOC_PATH, markdown) == [(DOC_PATH, 3, "not-utf8")]


def test_utf8_bytes_are_checked_like_text() -> None:
    assert _metadata_hits(DOC_PATH, _general_doc().encode()) == []


@pytest.mark.parametrize(
    "path", ["lab/2026-11-08-study/README.md", "data/raw/notes.md", "frontend/node_modules/a.md"]
)
def test_docs_outside_the_doc_scope_are_not_checked_for_metadata(path: str) -> None:
    assert _metadata_hits(path, "Research notes without a title.\n") == []


def test_first_block_after_the_h1_must_be_the_metadata_block() -> None:
    markdown = (
        "# Guide\n\nIntro paragraph.\n\n> - Created: 2026-10-01\n> - Last Updated: 2026-10-02\n"
    )

    assert _metadata_hits(DOC_PATH, markdown) == [
        (DOC_PATH, 3, "metadata-block-position"),
        (DOC_PATH, 5, "header-stray-key"),
        (DOC_PATH, 6, "header-stray-key"),
    ]


def test_doc_with_only_a_title_misses_its_metadata_block_on_the_title_line() -> None:
    assert _metadata_hits(DOC_PATH, "# Guide\n") == [(DOC_PATH, 1, "metadata-block-position")]


@pytest.mark.parametrize(
    "item",
    [
        "> - Author：Doc Author",
        "> Author: Doc Author",
        "> - **Author**: Doc Author",
        ">",
        "> - Author:",
    ],
)
def test_metadata_line_not_in_key_colon_value_form_is_a_violation(item: str) -> None:
    metadata = f"> - Created: 2026-10-01\n> - Last Updated: 2026-10-02\n{item}\n"

    assert _metadata_hits(DOC_PATH, _general_doc(metadata)) == [(DOC_PATH, 5, "metadata-item")]


def test_key_outside_the_whitelist_is_reported_with_the_allowed_keys() -> None:
    metadata = "> - Created: 2026-10-01\n> - Last Updated: 2026-10-02\n> - 專案版本: `0.4.0`\n"

    [violation] = doc_metadata_violations(DOC_PATH, _general_doc(metadata))

    assert (violation.line, violation.message.split(":", 1)[0]) == (5, "unknown-key")
    assert "Created, Last Updated, Author, Status, Related" in violation.message


def test_key_names_are_case_sensitive() -> None:
    metadata = "> - Created: 2026-10-01\n> - Last updated: 2026-10-02\n"

    assert (DOC_PATH, 4, "unknown-key") in _metadata_hits(DOC_PATH, _general_doc(metadata))


@pytest.mark.parametrize(
    "item",
    [
        "> - Supersedes: [ADR-0001](../adr/0001-title.md)",
        "> - Superseded by: [ADR-0015](../adr/0015-title.md)",
        "> - Revisions: [Notes](#notes)",
    ],
)
def test_adr_only_keys_do_not_apply_to_general_docs(item: str) -> None:
    metadata = f"> - Created: 2026-10-01\n> - Last Updated: 2026-10-02\n{item}\n"
    body = "## Notes\n\n- 2026-10-02：Revised.\n"

    hits = _metadata_hits(DOC_PATH, _general_doc(metadata, body=body))

    assert hits == [(DOC_PATH, 5, "key-not-applicable")]


def test_adr_may_carry_supersedes_superseded_by_and_revisions() -> None:
    metadata = (
        "> - Created: 2026-10-01\n> - Last Updated: 2026-10-02\n> - Status: Accepted\n"
        "> - Supersedes: [ADR-0002](0002-title.md)\n"
        "> - Superseded by: [ADR-0015](0015-title.md)\n"
        "> - Revisions: [Notes](#5-notes)\n"
    )

    assert _metadata_hits(ADR_PATH, _adr_doc(metadata, body="## 5. Notes\n\n- Note.\n")) == []


def test_repeated_key_is_reported_on_its_second_line() -> None:
    metadata = (
        "> - Created: 2026-10-01\n> - Last Updated: 2026-10-02\n"
        "> - Author: Doc Author\n> - Author: Other Author\n"
    )

    assert _metadata_hits(DOC_PATH, _general_doc(metadata)) == [(DOC_PATH, 6, "duplicate-key")]


def test_key_after_a_later_key_is_reported_with_the_expected_order() -> None:
    metadata = (
        "> - Created: 2026-10-01\n> - Related: [ADR-0001](../adr/0001-title.md)\n"
        "> - Last Updated: 2026-10-02\n"
    )

    [violation] = doc_metadata_violations(DOC_PATH, _general_doc(metadata))

    assert (violation.line, violation.message.split(":", 1)[0]) == (5, "key-order")
    assert "Created, Last Updated, Author, Status, Related" in violation.message


def test_missing_dates_are_reported_on_the_first_metadata_line() -> None:
    hits = _metadata_hits(DOC_PATH, _general_doc("> - Author: Doc Author\n"))

    assert hits == [(DOC_PATH, 3, "missing-key"), (DOC_PATH, 3, "missing-key")]


def test_status_is_required_in_an_adr_but_optional_in_a_general_doc() -> None:
    dates = "> - Created: 2026-10-01\n> - Last Updated: 2026-10-02\n"

    assert _metadata_hits(ADR_PATH, _adr_doc(dates)) == [(ADR_PATH, 3, "missing-key")]
    assert _metadata_hits(DOC_PATH, _general_doc(dates)) == []


@pytest.mark.parametrize(
    "value", ["2026-13-01", "2026/10/02", "2026-10-02（補充說明）", "2026-10-02, 2026-10-03"]
)
def test_date_that_is_not_a_single_valid_iso_date_is_a_violation(value: str) -> None:
    metadata = f"> - Created: 2026-10-01\n> - Last Updated: {value}\n"

    assert _metadata_hits(DOC_PATH, _general_doc(metadata)) == [(DOC_PATH, 4, "invalid-date")]


def test_last_updated_before_created_is_a_violation_on_the_last_updated_line() -> None:
    metadata = "> - Created: 2026-10-02\n> - Last Updated: 2026-10-01\n"

    assert _metadata_hits(DOC_PATH, _general_doc(metadata)) == [(DOC_PATH, 4, "date-order")]


def test_last_updated_on_the_created_day_is_in_order() -> None:
    metadata = "> - Created: 2026-10-02\n> - Last Updated: 2026-10-02\n"

    assert _metadata_hits(DOC_PATH, _general_doc(metadata)) == []


def _with_status(status: str) -> str:
    return f"> - Created: 2026-10-01\n> - Last Updated: 2026-10-02\n> - Status: {status}\n"


@pytest.mark.parametrize("status", ["Proposed", "Accepted", "Superseded", "Deprecated", "Rejected"])
def test_adr_accepts_its_lifecycle_statuses(status: str) -> None:
    assert _metadata_hits(ADR_PATH, _adr_doc(_with_status(status))) == []


@pytest.mark.parametrize("status", ["已接受", "accepted", "Open", "Accepted (2026-10-02)"])
def test_adr_rejects_other_statuses(status: str) -> None:
    assert _metadata_hits(ADR_PATH, _adr_doc(_with_status(status))) == [
        (ADR_PATH, 5, "status-value")
    ]


@pytest.mark.parametrize("status", ["Open", "Closed", "Obsolete"])
def test_general_doc_accepts_record_statuses(status: str) -> None:
    assert _metadata_hits(DOC_PATH, _general_doc(_with_status(status))) == []


@pytest.mark.parametrize("status", ["Accepted", "Superseded", "進行中"])
def test_general_doc_rejects_adr_and_free_text_statuses(status: str) -> None:
    assert _metadata_hits(DOC_PATH, _general_doc(_with_status(status))) == [
        (DOC_PATH, 5, "status-value")
    ]


@pytest.mark.parametrize(
    "related",
    [
        "[ADR-0006](../adr/0006-title.md)",
        "[ADR-0006](../adr/0006-title.md)、[Issue #30](https://github.com/o/r/issues/30)",
        "[資料契約 §5](data-contracts.md#5-dagster-artifact-序列化與信任邊界)",
    ],
)
def test_related_holding_only_links_joined_by_the_ideographic_comma_passes(related: str) -> None:
    metadata = f"> - Created: 2026-10-01\n> - Last Updated: 2026-10-02\n> - Related: {related}\n"

    assert _metadata_hits(DOC_PATH, _general_doc(metadata)) == []


@pytest.mark.parametrize(
    "related",
    [
        "[ADR-0006](../adr/0006-title.md)（補充）",
        "[ADR-0006](../adr/0006-title.md), [ADR-0007](../adr/0007-title.md)",
        "ADR-0006",
        "見 [ADR-0006](../adr/0006-title.md)",
    ],
)
def test_related_with_text_besides_links_is_a_violation(related: str) -> None:
    metadata = f"> - Created: 2026-10-01\n> - Last Updated: 2026-10-02\n> - Related: {related}\n"

    assert _metadata_hits(DOC_PATH, _general_doc(metadata)) == [(DOC_PATH, 5, "link-only")]


@pytest.mark.parametrize("key", ["Supersedes", "Superseded by"])
def test_adr_supersession_keys_hold_only_links(key: str) -> None:
    metadata = _with_status("Superseded") + f"> - {key}: ADR-0015\n"

    assert _metadata_hits(ADR_PATH, _adr_doc(metadata)) == [(ADR_PATH, 6, "link-only")]


@pytest.mark.parametrize(
    ("heading", "anchor"), [("## Notes", "#notes"), ("## 5. Notes", "#5-notes")]
)
def test_revisions_points_at_the_notes_h2_whatever_its_section_number(
    heading: str, anchor: str
) -> None:
    metadata = _with_status("Accepted") + f"> - Revisions: [Notes]({anchor})\n"
    body = f"## 1. Context\n\nBody.\n\n{heading}\n\n- 2026-10-02：§1 revised.\n"

    assert _metadata_hits(ADR_PATH, _adr_doc(metadata, body=body)) == []


@pytest.mark.parametrize(
    "revisions",
    [
        "[Context](#1-context)",
        "[Notes](#notes)",
        "[Notes](0002-title.md#notes)",
        "[Notes](#5-notes)、[Context](#1-context)",
        "see Notes",
    ],
)
def test_revisions_not_pointing_at_this_adrs_notes_h2_is_a_violation(revisions: str) -> None:
    metadata = _with_status("Accepted") + f"> - Revisions: {revisions}\n"
    body = "## 1. Context\n\nBody.\n\n## 5. Notes\n\n- 2026-10-02：§1 revised.\n"

    hits = _metadata_hits(ADR_PATH, _adr_doc(metadata, body=body))

    assert hits == [(ADR_PATH, 6, "revisions-target")]


def test_revisions_needs_a_notes_h2_to_point_at() -> None:
    metadata = _with_status("Accepted") + "> - Revisions: [Notes](#notes)\n"

    hits = _metadata_hits(ADR_PATH, _adr_doc(metadata, body="## Context\n\n### Notes\n"))

    assert hits == [(ADR_PATH, 6, "revisions-target")]


@pytest.mark.parametrize(
    "line",
    [
        "2026-10-02：補上 Related。",
        "- 2026-10-02 修正錯字",
        "> - **2026-10-02**：狀態改為已結案",
        "修訂：§2 改寫",
        "- **修訂紀錄**：見 Notes",
    ],
)
def test_dated_or_revision_line_in_the_header_is_a_violation(line: str) -> None:
    intro = f"Intro paragraph.\n\n{line}\n\n"

    hits = _metadata_hits(DOC_PATH, _general_doc(intro=intro))

    assert hits == [(DOC_PATH, 8, "header-dated-line")]


def test_dated_lines_after_the_first_h2_are_body_text() -> None:
    body = "## Notes\n\n- 2026-10-02：§1 revised.\n- 最後更新：2026-09-04（補充說明）。\n"

    assert _metadata_hits(DOC_PATH, _general_doc(body=body)) == []


@pytest.mark.parametrize(
    "line",
    [
        "- 專案版本：`0.4.0`",
        "- **目標讀者**：維運人員",
        "> - Status: Open",
        "Related: [ADR-0001](../adr/0001-title.md)",
        "> **最後更新**：2026",
        "> - **排除內容（Avoid）**：架構取捨",
        "- 狀態 (Status)：已接受",
        "- 關聯：[ADR-0001](../adr/0001-title.md)",
        "- 專案名稱：`shiro-mlops`",
        "- 候選 1 規格：[GitHub #72](https://github.com/owner/repo/issues/72)",
    ],
)
def test_metadata_or_legacy_key_outside_the_metadata_block_is_a_violation(line: str) -> None:
    intro = f"Intro paragraph.\n\n{line}\n\n"

    hits = _metadata_hits(DOC_PATH, _general_doc(intro=intro))

    assert hits == [(DOC_PATH, 8, "header-stray-key")]


def test_legacy_header_list_is_out_of_position_and_its_keys_are_stray() -> None:
    markdown = "# Guide\n\n- 建立日期：2026-10-01\n- 最後更新：2026-10-02\n\n## 1. Scope\n"

    assert _metadata_hits(DOC_PATH, markdown) == [
        (DOC_PATH, 3, "metadata-block-position"),
        (DOC_PATH, 3, "header-stray-key"),
        (DOC_PATH, 4, "header-stray-key"),
    ]


def test_intro_list_with_bold_terms_before_the_first_h2_is_not_a_stray_key() -> None:
    intro = (
        "本文件說明兩層設定：\n\n"
        "- **bootstrap 層**（`infra/bootstrap/`）：建立 state bucket。\n"
        "- **主層**（`infra/`）：其餘資源。\n"
        "- 狀態機的說明見正文。\n\n"
        "---\n\n"
    )

    assert _metadata_hits(DOC_PATH, _general_doc(intro=intro)) == []
