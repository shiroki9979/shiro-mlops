"""Check repository conventions that are mechanical enough to enforce in CI.

Checks:
  python-uv  Makefile recipes and CI `run:` commands (.yml and .yaml workflows) must not run a
             host python/python3, also not behind a wrapper (env, sudo, exec, command, nohup,
             nice), inside `sh -c`/`bash -c`, in `$(...)` or backticks, or in a case arm.
  docker-pins
             Each package a `pip install` or `uv pip install` in docker/Dockerfile* and
             frontend/Dockerfile* names must be pinned to an exact version with ==, unless the
             command reads a constraints file with -c (as exported from uv.lock); or read a lock
             file with -r instead. Values of options such as -r and -e (a local project) are not
             checked. RUN and ONBUILD RUN in shell or exec form are read, a heredoc body run by
             the shell included, with the same wrappers and nested shells as python-uv.
             Each image that FROM or COPY --from names in those Dockerfiles, and each `image:`
             in docker/docker-compose*.yml and *.yaml, must be written name:tag@sha256:<digest>:
             the digest pins it, the tag keeps it readable. A reference holding a variable is
             unpinned. Build stage names, stage indexes and scratch are not images.
             To fix: resolve the multi-platform index digest of the exact tag (`docker
             buildx imagetools inspect <name>:<tag>`) and append it to the reference.
  action-pins
             Each `uses:` in .github/workflows/*.yml and *.yaml, outside `run:` scripts, must
             name a full 40-character commit SHA; keep the release it is in as a trailing
             comment (`# v4.4.0`) for reviewers. Local ./ actions are skipped and docker://
             actions need name:tag@sha256:<digest>. Each astral-sh/setup-uv step must set
             `with: version:` to an exact uv release (X.Y.Z), written out or as
             `${{ env.NAME }}` naming a workflow-level `env:` entry that holds one.
             To fix: `git ls-remote https://github.com/<owner>/<repo> refs/tags/<release>^{}`
             (or the plain tag when it has no ^{} line) gives the commit SHA.
  terms      Tracked Markdown must not use banned terms; the preferred term is reported.
  doc-dates  Docs that --base...--head adds, modifies or renames must carry a last-updated header
             dated no earlier than the newest author date (in the author's timezone) of the
             non-merge commits in that range that change them outside their metadata block.
             A commit that only edits the metadata block, in the `> - Key: value` form or a
             legacy header list such as `- 建立日期：...`, or only renames the doc, does not count.
             A doc the range adds must also carry a created date no earlier than the author
             date of the commit that adds it, so a doc copied as a template gets its own date.
             Docs are the tracked .md files outside lab/ and data/, and outside .venv and
             node_modules at any depth.
  doc-metadata
             Each tracked doc in the working tree must follow the metadata contract: an H1 on
             line 1, then a `> - Key: value` metadata block. Each violation starts with its
             rule code; the rules and codes are in docs/reference/markdown-metadata.md. Only
             the docs in DOC_METADATA_MIGRATED_SCOPE are checked until every doc is migrated.
  debt-markers
             TODO/FIXME/HACK/XXX in tracked source files must name their tech-debt issue,
             as in `TODO(#123): ...` (see docs/agents/tech-debt.md).
  comment-refs
             Tracked Python comments must refer to things that exist: each path in a
             SYNC(...) tag must be a tracked file, other paths starting with a tracked top-level
             directory must exist, and ADR-NNNN needs a docs/adr/NNNN-*.md. Other paths with
             glob or placeholder characters (* ? [ ] < > { } $) are skipped.
             To fix: point the comment at the renamed path, or rewrite or delete it with the
             removed file. A path-like word that is really a name (an MLflow experiment, say)
             should refer to the constant holding it, not be reworded to dodge the check.
  comment-kinds
             Comment blocks in src/ and scripts/ Python files that --base..--head adds or
             modifies must start with an allowed kind. A block is full-line comments on
             adjacent lines at one indent, and only its first line carries the tag; a trailing
             comment is its own block. Changing any line of a block checks the whole block, and
             changing a code line checks the trailing comment on it. Allowed kinds:
               WHY-NOT(<name>): <reason>          a deliberate design someone might "fix"
               SYNC(<path>[, <path>...]): <note>  deliberate duplication; paths from the root
               TODO(#n), FIXME(#n), HACK(#n), XXX(#n)
                                                  tech debt, see docs/agents/tech-debt.md
               noqa or type: ignore followed by a reason; pragma, fmt:, ruff:;
               a shebang on line 1; a PEP 263 coding line on line 1 or 2
             A WHY-NOT name (its last dotted part) must be an identifier in the code it
             protects: after a full-line block, the next logical line (the rest of the statement
             when the block sits inside brackets), or the decorators plus the def or class line
             of a decorated definition; for a trailing comment, its own logical line. A
             full-line WHY-NOT is also checked when that code is changed or removed.
             To fix: delete a comment that only restates the code, dividers and section labels
             included (split functions or modules instead); turn design notes into WHY-NOT, sync
             reminders into SYNC, and to-dos into TODO(#n) once a tech-debt issue exists; give
             noqa and type: ignore a reason. When a WHY-NOT name is missing, move the comment
             onto the code it protects or correct the name, or delete it with removed code.
  blob-limits
             Each commit between --base and --head must not add or modify a file over 5 MiB,
             one whose extension is blocked (.parquet .pkl .joblib .onnx .ipynb .tfstate
             .tfvars .pem .key, any letter case; also as a dotfile's whole name, and with more
             after it for terraform.tfstate.backup and prod.tfvars.json), or a saved Terraform
             plan (tfplan, tfplan.json). Every commit is checked, not only --head: a file a
             later commit deletes stays in history once the branch is merged. What a merge
             brings in is checked in the commits it merges; the merge commit itself is checked
             for the files that differ from every parent, such as an untracked file swept in
             by `git add -A` while the merge was in progress.
             To fix: rewrite the branch (git rebase) so no commit adds the file, and keep it
             out of git with .gitignore.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import tokenize
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import TypeVar

REPO_ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = "Makefile"
WORKFLOW_GLOBS = (".github/workflows/*.yml", ".github/workflows/*.yaml")
DOCKERFILE_GLOBS = ("docker/Dockerfile*", "frontend/Dockerfile*")
COMPOSE_GLOBS = ("docker/docker-compose*.yml", "docker/docker-compose*.yaml")
EXCLUDED_DIRS = frozenset({"node_modules", ".venv"})
DOC_SCOPE_EXCLUDED_ROOTS = frozenset({"lab", "data"})
"""Top-level directories whose Markdown the doc checks skip, besides EXCLUDED_DIRS at any depth."""
# TODO(#396): drop this list once every doc in scope is migrated, so doc-metadata checks the
# whole doc scope and a new directory cannot slip past it.
DOC_METADATA_MIGRATED_SCOPE = (
    "docs/adr/",
    "docs/reference/",
    "docs/agents/",
    "docs/ROADMAP.md",
    "AGENTS.md",
    "README.md",
    "GLOSSARY.md",
    "CODING_STANDARDS.md",
    "frontend/README.md",
)
"""Docs already in the metadata format, one directory (ending in /) or file per line."""
COMMENT_KINDS_DIRS = ("src", "scripts")
CHECKS_REQUIRING_BASE = ("doc-dates", "comment-kinds", "blob-limits")

# Single source for terminology: banned term -> preferred replacement.
BANNED_TERMS = {
    "端口": "連接埠",
}

HOST_PYTHON = re.compile(r"(?:.*/)?python(?:3(?:\.\d+)?)?")
ENV_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
COMMAND_SEPARATORS = frozenset({";", ";;", "&", "&&", "|", "||", "|&", "(", ")"})
# Shell reserved words are syntax, so the word after them is still the command word.
RESERVED_WORDS = frozenset({"!", "{", "if", "then", "elif", "else", "while", "until", "do", "time"})
# WHY-NOT(WRAPPER_COMMANDS): a wrapper is not the command word; `sudo python3 x.py` would
# otherwise pass for a sudo call and hide the host python it runs.
WRAPPER_COMMANDS = frozenset({"env", "sudo", "exec", "command", "nohup", "nice"})
WRAPPER_VALUE_OPTIONS = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir"}),
    "sudo": frozenset({"-C", "-D", "-g", "-h", "-p", "-R", "-r", "-t", "-T", "-U", "-u"}),
    "nice": frozenset({"-n", "--adjustment"}),
}
NESTED_SHELL = re.compile(r"(?:.*/)?(?:ba|da|z|k)?sh")
YAML_MAPPING_KEY = re.compile(r"^\s*[A-Za-z0-9_-]+:(?:\s|$)")
MAKE_RECIPE_PREFIXES = "@-+"
LINE_CONTINUATION = "\\"

RUN_KEY = re.compile(r"^(?P<indent>\s*)(?:-\s+)?run:\s*(?P<value>.*)$")
BLOCK_SCALAR = re.compile(r"^(?P<style>[|>])[-+0-9]*\s*(?:#.*)?$")
FOLDED_STYLE = ">"
YAML_QUOTES = "\"'"

# WHY-NOT(DOCKERFILE_RUN): RUN's own flags (--mount=..., --network=...) are skipped, or a
# `RUN --mount=... pip install` would hide its unpinned packages behind the flag.
DOCKERFILE_RUN = re.compile(
    r"^\s*(?:ONBUILD\s+)?RUN\s+(?:--\S+\s+)*(?P<command>.*)$", re.IGNORECASE
)
# WHY-NOT(HEREDOC): a RUN heredoc's lines up to its delimiter are its body; read as Dockerfile
# lines they were skipped, so `RUN <<EOF` hid every install in it.
HEREDOC = re.compile(
    r"<<(?P<strip>-?)\s*(?P<quote>[\'\"]?)(?P<word>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)"
)
USES_KEY = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<quote>[\"']?)(?P<ref>[^\s\"'#]+)(?P=quote)")
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
TAGGED_DIGEST = re.compile(r":[^/:@]+@sha256:[0-9a-f]{64}$")
SETUP_UV_ACTION = "astral-sh/setup-uv"
WORKFLOW_ENV_KEY = "env:"
WORKFLOW_ENV_ENTRY = re.compile(r"^  (?P<name>[A-Za-z_][A-Za-z0-9_]*):\s*(?P<value>.*)$")
ENV_EXPRESSION = re.compile(r"\$\{\{\s*env\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
EXACT_VERSION = re.compile(r"\d+\.\d+\.\d+")
MAPPING_ENTRY = re.compile(r"^\s*(?:-\s+)?(?P<key>[A-Za-z0-9_-]+):\s*(?P<value>.*)$")
LOCAL_ACTION = "./"
DOCKER_ACTION = "docker://"
DOCKERFILE_FROM = re.compile(
    r"^\s*FROM\s+(?:--\S+\s+)*(?P<image>\S+)(?:\s+AS\s+(?P<stage>\S+))?", re.IGNORECASE
)
DOCKERFILE_COPY_FROM = re.compile(
    r"^\s*(?:ONBUILD\s+)?COPY\s+.*?--from=(?P<quote>[\"']?)(?P<image>[^\s\"']+)(?P=quote)",
    re.IGNORECASE,
)
SCRATCH_IMAGE = "scratch"
COMPOSE_IMAGE = re.compile(r"^\s*image:\s*(?P<quote>[\"']?)(?P<image>[^\s\"'#]+)(?P=quote)")
DOCKERFILE_COMMENT = re.compile(r"^\s*#")
PIP_PROGRAM = re.compile(r"(?:.*/)?pip(?:3(?:\.\d+)?)?")
UV_PROGRAM = re.compile(r"(?:.*/)?uv")
EXACT_PIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9._,-]*\])?===?[^\s,;<>=!~*]+")
# WHY-NOT(CONSTRAINT_OPTION): names installed under -c are not checked for == pins, since the
# constraints file (exported from uv.lock) pins them; requiring == as well would duplicate the lock.
CONSTRAINT_OPTION = re.compile(r"-c.*|--constraint(?:=.*)?")
REDIRECTION = re.compile(r"[<>&]*[<>][<>&]*")
SHELL_PUNCTUATION = frozenset("();<>|&")
# WHY-NOT(PIP_VALUE_OPTIONS): the values of -r and -e are skipped like any option value rather
# than checked for pins; checking them would report `-r requirements.txt` and `-e .` as unpinned
# packages, though a lock file or a local project pins through its own files.
PIP_VALUE_OPTIONS = frozenset(
    {"-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-i", "--index-url"}
    | {"--extra-index-url", "-f", "--find-links", "-t", "--target", "--prefix", "--root"}
    | {"--python", "-p", "--python-version", "--platform", "--implementation", "--abi"}
    | {"--only-binary", "--no-binary", "--src", "--upgrade-strategy", "--cache-dir", "--log"}
    | {"--proxy", "--cert", "--client-cert", "--timeout", "--retries", "--trusted-host"}
    | {"--exists-action", "-C", "--config-settings", "--config-setting", "--report"}
    | {"--index", "--default-index", "--index-strategy", "--keyring-provider", "--override"}
    | {"-P", "--upgrade-package", "--reinstall-package", "--resolution", "--prerelease"}
    | {"--extra", "--group", "--config-file", "--exclude-newer", "--link-mode"}
)

DEBT_MARKER = re.compile(r"\b(?P<marker>TODO|FIXME|HACK|XXX)\b(?!\(#\d+\))")
DEBT_MARKER_SUFFIXES = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".sh", ".sql", ".css", ".html", ".conf"}
    | {".toml", ".yml", ".yaml", ".tf", ".hcl", ".mjs", ".cjs"}
)
DEBT_MARKER_FILE_PREFIXES = ("Makefile", "Dockerfile")
# These files spell the markers out to define and test the check itself.
DEBT_MARKER_EXEMPT = frozenset(
    {
        "scripts/check_conventions.py",
        "tests/unit/test_check_conventions.py",
        "tests/integration/test_check_conventions_git.py",
    }
)

# WHY-NOT(PATH_CANDIDATE): glob and placeholder characters continue the match instead of ending
# it, so a pattern is skipped whole rather than cut down to a concrete-looking directory.
PATH_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9_./${}<>*?\[\]-])(?P<path>[A-Za-z0-9_.-]+/[A-Za-z0-9_./${}<>*?\[\]-]*)"
)
# WHY-NOT(PATH_PATTERN_CHARS): a pattern is skipped, not glob-matched against tracked files:
# `<topic>` and `{name}` are placeholders rather than globs, and an example glob that matches
# nothing today documents a layout, not a broken reference.
PATH_PATTERN_CHARS = frozenset("*?[]<>{}$")
ADR_REF = re.compile(r"\bADR-(?P<number>\d{4})\b")
ADR_FILE = re.compile(r"docs/adr/\d{4}-[^/]+\.md")

WHY_NOT_TAG = "WHY-NOT"
WHY_NOT = re.compile(r"WHY-NOT\((?P<name>[A-Za-z_][A-Za-z0-9_.]*)\):\s*\S")
NON_CODE_TOKENS = frozenset(
    {tokenize.COMMENT, tokenize.NL, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
)
SYNC_TAG = "SYNC"
SYNC = re.compile(r"SYNC\((?P<paths>[^()\s,][^()]*)\):\s*\S")
LINKED_DEBT_MARKER = re.compile(r"(?:TODO|FIXME|HACK|XXX)\(#\d+\)")
SHEBANG = "#!"
ENCODING_DECLARATION = re.compile(r"#.*?coding[:=][ \t]*[-\w.]+")
DECORATOR = "@"
SUPPRESSION = re.compile(
    r"(?P<directive>noqa(?::\s*[A-Z]+[0-9]+(?:\s*,\s*[A-Z]+[0-9]+)*)?|type:\s*ignore(?:\[[^\]]*\])?)"
    r"(?P<reason>.*)"
)
REASON_SEPARATORS = " \t-:;,\u2013\u2014"
TOOL_DIRECTIVE = re.compile(r"(?:pragma\b|fmt:|ruff:)")
ALLOWED_COMMENT_KINDS = (
    "WHY-NOT(<name>): <reason>, SYNC(<path>[, <path>...]): <note>, "
    "TODO/FIXME/HACK/XXX(#<issue>), or a tool directive (noqa or type: ignore followed by "
    "a reason, pragma, fmt:, ruff:, a shebang or coding line)"
)
HUNK_HEADER = re.compile(r"@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")
DIFF_FILE_HEADER = "diff --git "
DIFF_NEW_PATH = "+++ b/"

BLOB_SIZE_LIMIT = 5 * 1024 * 1024
BLOCKED_SUFFIXES = frozenset(
    {".parquet", ".pkl", ".joblib", ".onnx", ".ipynb", ".tfstate", ".tfvars", ".pem", ".key"}
)
# SYNC(.gitignore): the Terraform and secrets patterns there name the same files; a pattern
# added to one side only lets a state backup or a saved plan through the other.
BLOCKED_SUFFIX_FOLLOWERS = {".tfstate": None, ".tfvars": frozenset({".json"})}
"""Suffixes still blocked when more follow: any after `.tfstate`, only `.json` after `.tfvars`."""
# SYNC(scripts/plan_terraform.sh): its default --out writes these two names beside the .tf files.
BLOCKED_NAMES = frozenset({"tfplan", "tfplan.json"})
GITLINK_MODE = "160000"
DELETED_MODE = "000000"
MODIFIED = "M"
RENAMED = "R"
PAIRED_STATUSES = frozenset("RC")

LAST_UPDATED = re.compile(
    r"^\s*(?:[>*-]\s+)*(?:\*\*)?(?:最後更新|Last Updated)(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*"
    r"(?P<value>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
CREATED = re.compile(
    r"^\s*(?:[>*-]\s+)*(?:\*\*)?(?:建立日期|Created)(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*"
    r"(?P<value>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
METADATA_KEYS = (
    "Created",
    "Last Updated",
    "Author",
    "Status",
    "Related",
    "Supersedes",
    "Superseded by",
    "Revisions",
)
"""The keys a doc's metadata block may hold, in the order it must hold them."""
LEGACY_METADATA_KEYS = (
    "建立日期",
    "最後更新",
    "狀態",
    "專案版本",
    "目標象限",
    "目標讀者",
    "核心目標",
    "排除內容",
    "文件類型",
    "檢視基準",
    "前次檢視",
    "對應",
    "結論",
)
"""Header keys from before the metadata contract; they mark a legacy metadata block."""
METADATA_KEY_NAMES = frozenset(key.casefold() for key in (*METADATA_KEYS, *LEGACY_METADATA_KEYS))
METADATA_ITEM = re.compile(r"^(?:>\s*)?[-*]\s+(?:\*\*)?(?P<key>[^:：*]+?)(?:\*\*)?\s*[:：]")
ATX_H1 = re.compile(r"^#(?:\s|$)")
BLOCKQUOTE = ">"
STRICT_METADATA_ITEM = re.compile(r"^> - (?P<key>[^\s:：*][^:：*]*?): (?P<value>\S.*)$")
METADATA_ITEM_FORM = "write each line as `> - Key: value`, with a half-width colon and a value"
METADATA_BLOCK_EXPECTED = (
    "the first block after the H1 must be the metadata block, one `> - Key: value` line per key"
)
ADR_ONLY_METADATA_KEYS = frozenset({"Supersedes", "Superseded by", "Revisions"})
REQUIRED_METADATA_KEYS = ("Created", "Last Updated")
ADR_REQUIRED_METADATA_KEYS = (*REQUIRED_METADATA_KEYS, "Status")
METADATA_DATE_KEYS = frozenset({"Created", "Last Updated"})
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
ADR_STATUSES = ("Proposed", "Accepted", "Superseded", "Deprecated", "Rejected")
DOC_STATUSES = ("Open", "Closed", "Obsolete")
LINK_METADATA_KEYS = frozenset({"Related", "Supersedes", "Superseded by"})
MARKDOWN_LINK = r"\[[^\[\]]+\]\([^()\s]+\)"
LINK_LIST = re.compile(rf"{MARKDOWN_LINK}(?:、{MARKDOWN_LINK})*")
SAME_FILE_LINK = re.compile(r"\[[^\[\]]+\]\(#(?P<anchor>[^()\s]+)\)")
NOTES_H2 = re.compile(r"^## (?P<title>(?:\d+(?:\.\d+)*\.?\s+)?Notes)\s*$")
"""An ADR's Notes H2, with or without a section number such as `5.`."""
ATX_H2 = re.compile(r"^##(?:\s|$)")
HEADER_LINE_PREFIX = re.compile(r"^(?:\s*(?:>|-|\*\*))*\s*")
"""What a header line may open with before its text: blockquote, list and bold markers."""
HEADER_KEY = re.compile(
    r"(?P<key>[^:：*（(]+?)\s*(?:\*\*)?\s*(?:[（(][^()（）]*[)）])?\s*(?:\*\*)?\s*[:：]"
)
"""A `key:` opening a header line; a gloss such as `（Avoid）` or `(Status)` is not the key."""
REVISION_WORD = "修訂"


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


@dataclass(frozen=True)
class SourceLine:
    line: int
    text: str


@dataclass(frozen=True)
class UnpinnedInstall:
    line: int
    packages: tuple[str, ...]


@dataclass(frozen=True)
class TermHit:
    line: int
    term: str
    replacement: str


@dataclass(frozen=True)
class HeaderDate:
    line: int
    raw: str

    @property
    def value(self) -> date:
        return date.fromisoformat(self.raw)


@dataclass(frozen=True)
class PathChange:
    """How one commit changes a path: a git status letter and the path the content came from."""

    status: str
    source: str


@dataclass(frozen=True)
class CommittedFile:
    """A file version one commit adds or modifies."""

    commit: str
    path: str
    size: int


HitT = TypeVar("HitT", SourceLine, UnpinnedInstall)


# Check name -> runner; the single list of checks the CLI accepts.
CHECKS: dict[str, Callable[[argparse.Namespace], list[Violation]]] = {
    "python-uv": lambda args: check_python_uv(REPO_ROOT),
    "docker-pins": lambda args: check_docker_pins(REPO_ROOT),
    "action-pins": lambda args: check_action_pins(REPO_ROOT),
    "terms": lambda args: check_terms(REPO_ROOT),
    "doc-dates": lambda args: check_doc_dates(GitRange(REPO_ROOT, args.base, args.head)),
    "doc-metadata": lambda args: check_doc_metadata(REPO_ROOT),
    "debt-markers": lambda args: check_debt_markers(REPO_ROOT),
    "comment-refs": lambda args: check_comment_refs(REPO_ROOT),
    "comment-kinds": lambda args: check_comment_kinds(GitRange(REPO_ROOT, args.base, args.head)),
    "blob-limits": lambda args: check_blob_limits(GitRange(REPO_ROOT, args.base, args.head)),
}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        violations = run_checks(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Convention check could not run: {describe(error)}", file=sys.stderr)
        return 2
    return report(violations)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("checks", nargs="+", choices=list(CHECKS))
    range_checks = ", ".join(CHECKS_REQUIRING_BASE)
    parser.add_argument(
        "--base", help=f"base ref for {range_checks}, e.g. origin/dev or a PR base SHA"
    )
    parser.add_argument(
        "--head", default="HEAD", help=f"head ref for {range_checks} (default: HEAD)"
    )
    args = parser.parse_args(argv)
    for name in CHECKS_REQUIRING_BASE:
        if name in args.checks and not args.base:
            parser.error(f"{name} requires --base")
    return args


def run_checks(args: argparse.Namespace) -> list[Violation]:
    return [violation for name in args.checks for violation in CHECKS[name](args)]


def report(violations: list[Violation]) -> int:
    for violation in violations:
        print(violation, file=sys.stderr)
    if violations:
        print(f"{len(violations)} convention violation(s) found", file=sys.stderr)
        return 1
    print("Convention checks passed")
    return 0


def describe(error: Exception) -> str:
    if isinstance(error, subprocess.CalledProcessError):
        return f"{' '.join(error.cmd)} exited {error.returncode}: {(error.stderr or '').strip()}"
    return str(error)


def check_python_uv(repo_root: Path) -> list[Violation]:
    sources: list[tuple[Path, Callable[[str], list[SourceLine]]]] = [
        (repo_root / MAKEFILE, find_host_python_in_makefile)
    ]
    sources += [(path, find_host_python_in_workflow) for path in globbed(repo_root, WORKFLOW_GLOBS)]
    return [
        violation
        for path, find in sources
        for violation in file_violations(repo_root, path, find, host_python_message)
    ]


def file_violations(
    repo_root: Path,
    path: Path,
    find: Callable[[str], list[HitT]],
    message: Callable[[HitT], str],
) -> list[Violation]:
    label = relative(path, repo_root)
    try:
        hits = find(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ValueError(f"{label}: {error}") from error
    return [Violation(label, hit.line, message(hit)) for hit in hits]


def host_python_message(command: SourceLine) -> str:
    return f"run Python through uv (`uv run ...`) instead of `{command.text.strip()}`"


def find_host_python_in_makefile(text: str) -> list[SourceLine]:
    commands = logical_commands(makefile_recipe_blocks(text))
    return [
        command for command in map(strip_recipe_prefix, commands) if starts_host_python(command)
    ]


def find_host_python_in_workflow(text: str) -> list[SourceLine]:
    commands = logical_commands(workflow_run_blocks(text))
    return [command for command in commands if starts_host_python(command)]


def makefile_recipe_blocks(text: str) -> list[list[SourceLine]]:
    blocks: list[list[SourceLine]] = [[]]
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("\t"):
            blocks[-1].append(SourceLine(number, line.strip()))
        elif blocks[-1]:
            blocks.append([])
    return [block for block in blocks if block]


def strip_recipe_prefix(command: SourceLine) -> SourceLine:
    return SourceLine(command.line, command.text.lstrip(MAKE_RECIPE_PREFIXES))


def workflow_run_blocks(text: str) -> list[list[SourceLine]]:
    lines = text.splitlines()
    blocks = []
    for index, line in enumerate(lines):
        match = RUN_KEY.match(line)
        if match is None:
            continue
        value = match["value"].strip()
        key_column = line.index("run:")
        scalar = BLOCK_SCALAR.match(value)
        if scalar is not None:
            blocks.append(block_scalar(lines, index, key_column, scalar["style"]))
        elif value:
            blocks.append([SourceLine(index + 1, unquote_yaml(value))])
        elif (plain := plain_scalar_below(lines, index, key_column)) is not None:
            blocks.append([plain])
    return blocks


def plain_scalar_below(lines: list[str], key_index: int, key_column: int) -> SourceLine | None:
    """A plain scalar that starts on the line after `run:`, folded into one command.

    A mapping under `run:` (as in `defaults: run: working-directory: ...`) is not a command.
    """
    block = block_scalar(lines, key_index, key_column, FOLDED_STYLE)
    if not block or YAML_MAPPING_KEY.match(lines[block[0].line - 1]):
        return None
    return block[0]


def block_scalar(lines: list[str], key_index: int, key_indent: int, style: str) -> list[SourceLine]:
    block = []
    for number, line in enumerate(lines[key_index + 1 :], start=key_index + 2):
        if line.strip() and indentation(line) <= key_indent:
            break
        block.append(SourceLine(number, line.strip()))
    if style == FOLDED_STYLE and block:
        # A folded scalar joins its lines into one command, so a line is not a command start.
        return [SourceLine(block[0].line, " ".join(line.text for line in block if line.text))]
    return block


def indentation(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def unquote_yaml(value: str) -> str:
    if len(value) > 1 and value[0] == value[-1] and value[0] in YAML_QUOTES:
        return value[1:-1]
    return value


def logical_commands(blocks: Iterable[list[SourceLine]]) -> list[SourceLine]:
    return [command for block in blocks for command in join_continuations(block)]


def join_continuations(block: list[SourceLine]) -> list[SourceLine]:
    """Join backslash continuations and quotes spanning lines into single shell commands."""
    commands: list[SourceLine] = []
    pending: list[SourceLine] = []
    for line in block:
        pending.append(line)
        text = join_lines(pending)
        if line.text.endswith(LINE_CONTINUATION) or shell_tokens(text) is None:
            continue
        commands.append(SourceLine(pending[0].line, text))
        pending = []
    if pending:
        commands.append(SourceLine(pending[0].line, join_lines(pending)))
    return commands


def join_lines(lines: list[SourceLine]) -> str:
    text = ""
    for line in lines:
        if text.endswith(LINE_CONTINUATION):
            text = text[: -len(LINE_CONTINUATION)] + " " + line.text
        else:
            text = f"{text}\n{line.text}" if text else line.text
    return text


def shell_tokens(text: str) -> list[str] | None:
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def starts_host_python(command: SourceLine) -> bool:
    return any(HOST_PYTHON.fullmatch(run[0]) for run in parsed_commands(command))


def parsed_commands(command: SourceLine) -> list[list[str]]:
    tokens = shell_tokens(command.text)
    if tokens is None:
        raise ValueError(f"line {command.line}: cannot parse shell command {command.text!r}")
    return commands_in(tokens, command.text)


def commands_in(tokens: list[str], text: str | None) -> list[list[str]]:
    """Every simple command the shell would run, each from its real command word.

    A wrapper (`env`, `sudo`, `exec`, ...) runs the command after its options, `sh -c` runs
    its script, and `$(...)` or backticks in `text` run what they enclose; each of these
    used to pass for the wrapper or the outer command alone.
    """
    commands = [run for simple in simple_commands(tokens) for run in unwrapped(simple)]
    if text is not None:
        for inner in command_substitutions(text):
            commands += nested_commands(inner)
    return commands


def nested_commands(text: str) -> list[list[str]]:
    tokens = shell_tokens(text)
    return [] if tokens is None else commands_in(tokens, text)


def unwrapped(command: list[str]) -> list[list[str]]:
    command = list(command)
    while command and command[0] in WRAPPER_COMMANDS:
        wrapper = command.pop(0)
        value_options = WRAPPER_VALUE_OPTIONS.get(wrapper, frozenset())
        while command and (
            command[0].startswith("-") or (wrapper == "env" and ENV_ASSIGNMENT.match(command[0]))
        ):
            if command.pop(0) in value_options and command:
                command.pop(0)
    if not command:
        return []
    if NESTED_SHELL.fullmatch(command[0]):
        for position, token in enumerate(command[1:], start=1):
            if not token.startswith("-") or token.startswith("--"):
                break
            if "c" in token[1:]:
                script = command[position + 1] if position + 1 < len(command) else ""
                return [command, *nested_commands(script)]
    return [command]


def command_substitutions(text: str) -> list[str]:
    """The text inside each `$(...)` and backtick pair outside single quotes."""
    found: list[str] = []
    index, quote = 0, None
    while index < len(text):
        char = text[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if char in "'\"" and quote in (None, char):
            quote = None if quote == char else char
        elif quote != "'" and text.startswith("$(", index):
            end = matching_parenthesis(text, index + 1)
            found.append(text[index + 2 : end])
            index = end
        elif quote != "'" and char == "`":
            end = text.find("`", index + 1)
            end = len(text) if end == -1 else end
            found.append(text[index + 1 : end])
            index = end
        index += 1
    return found


def matching_parenthesis(text: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return len(text)


def check_docker_pins(repo_root: Path) -> list[Violation]:
    dockerfiles = globbed(repo_root, DOCKERFILE_GLOBS)
    violations = [
        violation
        for path in dockerfiles
        for violation in file_violations(
            repo_root, path, find_unpinned_pip_installs, unpinned_message
        )
        + file_violations(repo_root, path, find_unpinned_images, unpinned_image_message)
    ]
    violations += [
        violation
        for path in globbed(repo_root, COMPOSE_GLOBS)
        for violation in file_violations(
            repo_root, path, find_unpinned_compose_images, unpinned_image_message
        )
    ]
    return sorted(violations, key=lambda violation: (violation.path, violation.line))


def check_action_pins(repo_root: Path) -> list[Violation]:
    return [
        violation
        for path in globbed(repo_root, WORKFLOW_GLOBS)
        for violation in sorted(
            file_violations(repo_root, path, find_unpinned_actions, unpinned_action_message)
            + file_violations(repo_root, path, find_unpinned_uv_setups, unpinned_uv_message),
            key=lambda violation: violation.line,
        )
    ]


def globbed(repo_root: Path, globs: Iterable[str]) -> list[Path]:
    return sorted(path for glob in globs for path in repo_root.glob(glob))


def unpinned_image_message(hit: SourceLine) -> str:
    return f"pin images to a digest, as in name:tag@sha256:<digest>: {hit.text}"


def unpinned_action_message(hit: SourceLine) -> str:
    return f"pin actions to a full commit SHA, with the release as a comment: {hit.text}"


def unpinned_uv_message(hit: SourceLine) -> str:
    return (
        "set setup-uv `with: version:` to an exact uv release (X.Y.Z), not: "
        f"{hit.text or '(missing)'}"
    )


def unpinned_message(hit: UnpinnedInstall) -> str:
    packages = ", ".join(hit.packages)
    return f"pin pip installs with ==, or install under a lock file with -c or -r: {packages}"


def find_unpinned_pip_installs(text: str) -> list[UnpinnedInstall]:
    hits = []
    for run in dockerfile_run_commands(text):
        exec_form = dockerfile_exec_form(run.text)
        commands = commands_in(exec_form, None) if exec_form is not None else parsed_commands(run)
        packages = tuple(package for command in commands for package in unpinned_packages(command))
        if packages:
            hits.append(UnpinnedInstall(run.line, packages))
    return hits


def find_unpinned_images(text: str) -> list[SourceLine]:
    """Images that FROM or COPY --from names without a digest; build stages are not images."""
    stages = {SCRATCH_IMAGE}
    hits = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = DOCKERFILE_FROM.match(line) or DOCKERFILE_COPY_FROM.match(line)
        if match is None:
            continue
        image = match["image"]
        if image.lower() not in stages and not image.isdigit() and not TAGGED_DIGEST.search(image):
            hits.append(SourceLine(number, image))
        if match.re is DOCKERFILE_FROM and match["stage"]:
            stages.add(match["stage"].lower())
    return hits


def find_unpinned_compose_images(text: str) -> list[SourceLine]:
    """Compose `image:` values without a digest."""
    return [
        SourceLine(number, match["image"])
        for number, line in enumerate(text.splitlines(), start=1)
        if (match := COMPOSE_IMAGE.match(line)) and not TAGGED_DIGEST.search(match["image"])
    ]


def dockerfile_exec_form(command: str) -> list[str] | None:
    """The argument list of `RUN ["pip", "install", ...]`, which runs without a shell."""
    if not command.lstrip().startswith("["):
        return None
    try:
        arguments = json.loads(command)
    except ValueError:
        return None
    if not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments):
        return None
    return arguments


def dockerfile_run_commands(text: str) -> list[SourceLine]:
    """Join each RUN instruction's continuation lines into one shell command.

    A heredoc's body runs as shell commands when nothing but a shell takes it, and each
    of those is reported at its RUN line; its lines are never read as instructions.
    """
    lines = text.splitlines()
    runs: list[SourceLine] = []
    pending: list[SourceLine] = []
    index = 0
    while index < len(lines):
        number, line = index + 1, lines[index]
        index += 1
        if pending and DOCKERFILE_COMMENT.match(line):
            continue
        if not pending:
            match = DOCKERFILE_RUN.match(line)
            if match is None:
                continue
            line = match["command"]
        pending.append(SourceLine(number, line.strip()))
        if line.rstrip().endswith(LINE_CONTINUATION):
            continue
        run = SourceLine(pending[0].line, join_lines(pending))
        pending = []
        markers = list(HEREDOC.finditer(run.text))
        if not markers:
            runs.append(run)
            continue
        command = HEREDOC.sub("", run.text).strip()
        runs.append(SourceLine(run.line, command))
        for marker in markers:
            body, index = heredoc_body(lines, index, marker)
            if not command or NESTED_SHELL.fullmatch(command.split()[0]):
                runs += [SourceLine(run.line, line.text) for line in join_continuations(body)]
    if pending:
        runs.append(SourceLine(pending[0].line, join_lines(pending)))
    return runs


def heredoc_body(
    lines: list[str], start: int, marker: re.Match[str]
) -> tuple[list[SourceLine], int]:
    """The heredoc's lines from `start` up to its delimiter, and the index after it."""
    body: list[SourceLine] = []
    for index in range(start, len(lines)):
        line = lines[index].lstrip("\t") if marker["strip"] else lines[index]
        if line == marker["word"]:
            return body, index + 1
        body.append(SourceLine(index + 1, line.strip()))
    return body, len(lines)


def simple_commands(tokens: list[str]) -> list[list[str]]:
    """Split shell tokens into commands, each starting at its command word."""
    commands: list[list[str]] = [[]]
    for token in tokens:
        if token in COMMAND_SEPARATORS:
            commands.append([])
        elif commands[-1] or not (token in RESERVED_WORDS or ENV_ASSIGNMENT.match(token)):
            commands[-1].append(token)
    return [command for command in commands if command]


def unpinned_packages(command: list[str]) -> list[str]:
    packages = []
    takes_value = False
    for token in without_redirections(pip_install_arguments(command)):
        if takes_value:
            takes_value = False
        elif CONSTRAINT_OPTION.fullmatch(token):
            return []
        elif token.startswith("-"):
            takes_value = token in PIP_VALUE_OPTIONS
        elif not EXACT_PIN.fullmatch(token):
            packages.append(token)
    return packages


def without_redirections(arguments: list[str]) -> list[str]:
    kept: list[str] = []
    skip_target = False
    for token in arguments:
        if skip_target:
            skip_target = False
        elif REDIRECTION.fullmatch(token):
            if kept and kept[-1].isdigit():
                kept.pop()
            skip_target = True
        elif not set(token) <= SHELL_PUNCTUATION:
            kept.append(token)
    return kept


def pip_install_arguments(command: list[str]) -> list[str]:
    """Return the arguments after `install` when the command runs a pip installer, else []."""
    program, *rest = command
    if PIP_PROGRAM.fullmatch(program):
        subcommand = ["install"]
    elif UV_PROGRAM.fullmatch(program):
        subcommand = ["pip", "install"]
    elif HOST_PYTHON.fullmatch(program):
        subcommand = ["-m", "pip", "install"]
    else:
        return []
    position = 0
    skips_values = not HOST_PYTHON.fullmatch(program)
    for word in subcommand:
        while position < len(rest) and rest[position] != word and rest[position].startswith("-"):
            # WHY-NOT(takes_value): in `pip --cache-dir /tmp/c install`, the value /tmp/c is not
            # the subcommand; without skipping it, the install after it was never checked.
            takes_value = skips_values and rest[position] in PIP_VALUE_OPTIONS
            position += 2 if takes_value else 1
        if position == len(rest) or rest[position] != word:
            return []
        position += 1
    return rest[position:]


def find_unpinned_actions(text: str) -> list[SourceLine]:
    """`uses:` references that do not name a full commit SHA (or a digest, for docker://)."""
    hits = []
    for index, ref in workflow_uses(text):
        if ref.startswith(LOCAL_ACTION):
            continue
        if ref.startswith(DOCKER_ACTION):
            pinned = TAGGED_DIGEST.search(ref) is not None
        else:
            _, _, version = ref.partition("@")
            pinned = COMMIT_SHA.fullmatch(version) is not None
        if not pinned:
            hits.append(SourceLine(index + 1, ref))
    return hits


def find_unpinned_uv_setups(text: str) -> list[SourceLine]:
    """setup-uv steps whose `with: version:` is missing or not an exact uv release.

    A `${{ env.NAME }}` version is read from the workflow-level `env:`. Each hit is reported
    at its version line, or at the `uses:` line when there is none; its text is the version as
    written, empty when missing.
    """
    lines = text.splitlines()
    env = workflow_env(lines)
    hits = []
    for index, ref in workflow_uses(text):
        if ref.partition("@")[0] != SETUP_UV_ACTION:
            continue
        key_column = lines[index].index("uses:")
        version = step_with_value(lines, step_lines(lines, index, key_column), "version")
        if version is None:
            hits.append(SourceLine(index + 1, ""))
        elif not EXACT_VERSION.fullmatch(resolve_env(version.text, env)):
            hits.append(version)
    return hits


def workflow_uses(text: str) -> list[tuple[int, str]]:
    """(line index, ref) of each `uses:` key, skipping lines of `run:` scripts."""
    script_lines = {line.line for block in workflow_run_blocks(text) for line in block}
    return [
        (index, match["ref"])
        for index, line in enumerate(text.splitlines())
        if index + 1 not in script_lines and (match := USES_KEY.match(line))
    ]


def workflow_env(lines: list[str]) -> dict[str, str]:
    """The workflow-level `env:` entries, unquoted."""
    env: dict[str, str] = {}
    in_env = False
    for line in lines:
        if line and not line[0].isspace():
            in_env = line.rstrip() == WORKFLOW_ENV_KEY
        elif in_env and (entry := WORKFLOW_ENV_ENTRY.match(line)):
            env[entry["name"]] = unquote_yaml(entry["value"].split(" #", 1)[0].strip())
    return env


def resolve_env(value: str, env: dict[str, str]) -> str:
    expression = ENV_EXPRESSION.fullmatch(value)
    return env.get(expression["name"], value) if expression else value


def step_lines(lines: list[str], index: int, key_column: int) -> range:
    """The indexes of the workflow step whose keys start at `key_column` around `index`.

    The step starts at its `- ` line, the first line above `index` indented less than its
    keys; blank and comment lines do not end it.
    """
    start = index
    while start > 0 and indentation(lines[start]) >= key_column:
        start -= 1
        while start > 0 and lines[start].strip()[:1] in ("", "#"):
            start -= 1
    end = index + 1
    while end < len(lines) and (not lines[end].strip() or indentation(lines[end]) >= key_column):
        end += 1
    return range(start, end)


def step_with_value(lines: list[str], step: range, key: str) -> SourceLine | None:
    """The value of `key` directly under the step's `with:`, unquoted and without its comment."""
    with_column = child_column = None
    for index in step:
        entry = MAPPING_ENTRY.match(lines[index])
        if entry is None:
            continue
        column = lines[index].index(entry["key"])
        if with_column is not None and column <= with_column:
            with_column = child_column = None
        if entry["key"] == "with" and with_column is None:
            with_column = column
        elif with_column is not None:
            child_column = column if child_column is None else child_column
            if column == child_column and entry["key"] == key:
                value = entry["value"].split(" #", 1)[0].strip()
                return SourceLine(index + 1, unquote_yaml(value))
    return None


def check_terms(repo_root: Path) -> list[Violation]:
    return [
        Violation(path, hit.line, f"banned term '{hit.term}'; use '{hit.replacement}'")
        for path in tracked_markdown(repo_root)
        for hit in find_banned_terms((repo_root / path).read_text(encoding="utf-8"))
    ]


def check_doc_metadata(repo_root: Path) -> list[Violation]:
    return [
        violation
        for path in tracked_markdown(repo_root)
        if is_doc_metadata_migrated(path)
        for violation in doc_metadata_violations(path, (repo_root / path).read_bytes())
    ]


def is_doc_metadata_migrated(path: str) -> bool:
    return any(
        path == entry or (entry.endswith("/") and path.startswith(entry))
        for entry in DOC_METADATA_MIGRATED_SCOPE
    )


def tracked_markdown(repo_root: Path) -> list[str]:
    return tracked_files(repo_root, "*.md")


def tracked_files(repo_root: Path, *pathspecs: str) -> list[str]:
    paths = git(repo_root, "ls-files", "-z", "--", *pathspecs).split("\0")
    return [path for path in paths if path and not EXCLUDED_DIRS.intersection(Path(path).parts)]


def find_banned_terms(text: str) -> list[TermHit]:
    return [
        TermHit(number, term, replacement)
        for number, line in enumerate(text.splitlines(), start=1)
        for term, replacement in BANNED_TERMS.items()
        if term in line
    ]


def check_debt_markers(repo_root: Path) -> list[Violation]:
    return [
        Violation(
            path, hit.line, f"'{hit.text}' must name its tech-debt issue, e.g. {hit.text}(#123)"
        )
        for path in tracked_files(repo_root)
        if is_debt_marker_source(path)
        for hit in find_unlinked_debt_markers((repo_root / path).read_text(encoding="utf-8"))
    ]


def is_debt_marker_source(path: str) -> bool:
    parts = Path(path).parts
    if path in DEBT_MARKER_EXEMPT or EXCLUDED_DIRS.intersection(parts):
        return False
    name = parts[-1]
    return name.startswith(DEBT_MARKER_FILE_PREFIXES) or Path(name).suffix in DEBT_MARKER_SUFFIXES


def find_unlinked_debt_markers(text: str) -> list[SourceLine]:
    return [
        SourceLine(number, match["marker"])
        for number, line in enumerate(text.splitlines(), start=1)
        for match in DEBT_MARKER.finditer(line)
    ]


def check_comment_refs(repo_root: Path) -> list[Violation]:
    tracked = tracked_files(repo_root)
    tree = TrackedTree(tracked)
    adrs = {Path(path).name[:4] for path in tracked if ADR_FILE.fullmatch(path)}
    return [
        Violation(path, comment.line, message)
        for path in tracked
        if path.endswith(".py")
        for comment in source_comments(path, (repo_root / path).read_text(encoding="utf-8"))
        for message in comment_ref_problems(comment, tree, adrs)
    ]


def source_comments(path: str, source: str) -> list[Comment]:
    try:
        return list(python_comments(source))
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error


def comment_ref_problems(comment: Comment, tree: TrackedTree, adrs: set[str]) -> list[str]:
    sync_paths = comment_kind(comment).sync_paths
    problems = [
        f"SYNC path '{path}' is not a tracked file; list each file to change together by its "
        "path from the repository root, or update the list if a file was renamed or removed"
        for path in sync_paths
        if path not in tree.files
    ]
    problems += [
        f"comment refers to missing path '{ref}'; point it at the renamed path, or rewrite or "
        "delete it if the file was removed"
        for ref in find_path_refs(comment.text, tree.top_level_dirs)
        if ref not in sync_paths and not tree.contains(ref)
    ]
    problems += [
        f"comment refers to {match[0]}, but docs/adr/ has no {match['number']}-*.md"
        for match in ADR_REF.finditer(comment.text)
        if match["number"] not in adrs
    ]
    return problems


def find_path_refs(text: str, top_level_dirs: Iterable[str]) -> list[str]:
    refs = []
    for match in PATH_CANDIDATE.finditer(text):
        candidate = match["path"].rstrip(".")
        top, _, rest = candidate.partition("/")
        if top in top_level_dirs and rest and not PATH_PATTERN_CHARS.intersection(candidate):
            refs.append(candidate)
    return refs


class TrackedTree:
    """The tracked files of a repository, queried as a tree of files and directories."""

    def __init__(self, tracked: Iterable[str]) -> None:
        self.files = frozenset(tracked)
        self.dirs = frozenset(
            "/".join(parts[:end])
            for parts in (Path(path).parts for path in self.files)
            for end in range(1, len(parts))
        )
        self.top_level_dirs = frozenset(path for path in self.dirs if "/" not in path)

    def contains(self, path: str) -> bool:
        stripped = path.rstrip("/")
        return stripped in self.dirs or (stripped == path and path in self.files)


def check_comment_kinds(revisions: GitRange) -> list[Violation]:
    return [
        violation
        for path, changes in revisions.changed_lines(*COMMENT_KINDS_DIRS).items()
        if path.endswith(".py")
        for violation in comment_kind_violations(path, revisions.read_at_head(path), changes)
    ]


def comment_kind_violations(path: str, source: str, changes: FileChanges) -> list[Violation]:
    """Check each comment block that `changes` touches, or whose WHY-NOT anchor code it touches."""
    code = logical_lines(source)
    violations = []
    for block in comment_blocks(source_comments(path, source)):
        kind = comment_kind(block.first)
        anchor = why_not_anchor(kind.why_not, block, code) if kind.why_not is not None else None
        anchor_changed = (
            anchor is not None
            and block.first.full_line
            and changes.touches_after(block.last_line, anchor.last_line)
        )
        if not (changes.touches(block.lines) or anchor_changed):
            continue
        problem = kind.problem or (anchor.problem() if anchor is not None else None)
        if problem is not None:
            violations.append(Violation(path, block.first.line, problem))
    return violations


@dataclass(frozen=True)
class CommentBlock:
    """Comments read as one unit; only the first one carries the kind tag."""

    comments: tuple[Comment, ...]

    @property
    def first(self) -> Comment:
        return self.comments[0]

    @property
    def last_line(self) -> int:
        return self.comments[-1].line

    @property
    def lines(self) -> set[int]:
        return {comment.line for comment in self.comments}


def comment_blocks(comments: Iterable[Comment]) -> list[CommentBlock]:
    """Group full-line comments on adjacent lines at one indent; a trailing comment stands alone."""
    groups: list[list[Comment]] = []
    for comment in comments:
        previous = groups[-1][-1] if groups else None
        if previous is not None and continues_block(previous, comment):
            groups[-1].append(comment)
        else:
            groups.append([comment])
    return [CommentBlock(tuple(group)) for group in groups]


def continues_block(previous: Comment, comment: Comment) -> bool:
    return (
        previous.full_line
        and comment.full_line
        and comment.line == previous.line + 1
        and comment.column == previous.column
        and not is_file_directive(previous)
        and not is_file_directive(comment)
    )


def is_file_directive(comment: Comment) -> bool:
    """A shebang on line 1 or a PEP 263 encoding declaration on line 1 or 2."""
    if comment.line == 1 and comment.text.startswith(SHEBANG):
        return True
    return (
        comment.line <= 2 and comment.full_line and bool(ENCODING_DECLARATION.match(comment.text))
    )


@dataclass(frozen=True)
class CommentKind:
    """What the first comment of a block declares, or why it is not an allowed kind."""

    problem: str | None = None
    why_not: str | None = None
    sync_paths: tuple[str, ...] = ()


def comment_kind(comment: Comment) -> CommentKind:
    body = comment.body
    if body.startswith(WHY_NOT_TAG):
        if (why_not := WHY_NOT.match(body)) is not None:
            return CommentKind(why_not=why_not["name"])
        return CommentKind(
            "WHY-NOT comment must read `WHY-NOT(<name>): <reason>`, naming the code it protects"
        )
    if body.startswith(SYNC_TAG):
        if (sync := SYNC.match(body)) is not None:
            return CommentKind(sync_paths=tuple(path.strip() for path in sync["paths"].split(",")))
        return CommentKind(
            "SYNC comment must read `SYNC(<path>[, <path>...]): <note>` with repo-rooted paths"
        )
    if LINKED_DEBT_MARKER.match(body) or TOOL_DIRECTIVE.match(body) or is_file_directive(comment):
        return CommentKind()
    suppression = SUPPRESSION.match(body)
    if suppression is not None:
        if suppression["reason"].strip(REASON_SEPARATORS):
            return CommentKind()
        directive = suppression["directive"]
        return CommentKind(
            f"`{directive}` needs a reason after it, e.g. `# {directive} — <why it is needed>`"
        )
    return CommentKind(
        f"comment block does not start with an allowed kind ({ALLOWED_COMMENT_KINDS}); "
        "delete it if the code already says it, otherwise tag its first line "
        "(`scripts/check_conventions.py --help` explains each kind)"
    )


@dataclass(frozen=True)
class Anchor:
    """The code a WHY-NOT name must appear in, and how to describe where it was looked for."""

    name: str
    tokens: tuple[CodeToken, ...]
    where: str

    @property
    def last_line(self) -> int | None:
        return self.tokens[-1].line if self.tokens else None

    def problem(self) -> str | None:
        """Require the name among the anchor's identifiers; a dotted name matches its last part."""
        name = self.name.rpartition(".")[2]
        if any(token.is_name and token.text == name for token in self.tokens):
            return None
        named = f"'{name}'" if name == self.name else f"'{name}' (from '{self.name}')"
        return (
            f"WHY-NOT name {named} must appear on {self.where}; move the comment onto the code "
            "it protects or correct the name, and delete it along with code that was removed"
        )


def why_not_anchor(name: str, block: CommentBlock, code: list[LogicalLine]) -> Anchor:
    """Find the code a WHY-NOT block protects: the next statement, or its own for a trailing one."""
    if not block.first.full_line:
        tokens = next(
            (line.tokens for line in reversed(code) if line.first <= block.first.line), ()
        )
        return Anchor(name, tokens, f"the same logical line (line {block.first.line})")
    end = block.last_line
    index = next((index for index, line in enumerate(code) if line.ends_after(end)), None)
    if index is None:
        return Anchor(name, (), "the next logical line, but no code follows the comment")
    if code[index].first > end and code[index].is_decorator:
        tokens = decorated_definition(code, index)
        lines = f"lines {tokens[0].line}-{tokens[-1].line}"
        return Anchor(name, tokens, f"the decorated definition ({lines})")
    tokens = code[index].tokens_after(end)
    return Anchor(name, tokens, f"the next logical line (line {tokens[0].line})")


def decorated_definition(code: list[LogicalLine], index: int) -> tuple[CodeToken, ...]:
    """Tokens of the decorators starting at `code[index]` and of the `def` or `class` line after."""
    end = index
    while end < len(code) and code[end].is_decorator:
        end += 1
    return tuple(token for line in code[index : end + 1] for token in line.tokens)


def check_blob_limits(revisions: GitRange) -> list[Violation]:
    return [
        Violation(committed.path, 1, problem)
        for committed in revisions.committed_files()
        for problem in committed_file_problems(committed)
    ]


def committed_file_problems(committed: CommittedFile) -> list[str]:
    commit = committed.commit[:7]
    fix = "rewrite the branch so no commit adds it (git rebase) and keep it out with .gitignore"
    problems = []
    blocked = blocked_file_kind(committed.path)
    if blocked is not None:
        problems.append(f"commit {commit} adds a blocked '{blocked}' file; {fix}")
    if committed.size > BLOB_SIZE_LIMIT:
        size = committed.size / 1024 / 1024
        limit = BLOB_SIZE_LIMIT // 1024 // 1024
        problems.append(f"commit {commit} adds {size:.1f} MiB, over the {limit} MiB limit; {fix}")
    return problems


def blocked_file_kind(path: str) -> str | None:
    """The suffix or file name that blocks `path`, as the commit spelled it, or None.

    A dotfile's whole name counts as its suffix (`.pem`), and the suffixes in
    `BLOCKED_SUFFIX_FOLLOWERS` stay blocked with more after them (`terraform.tfstate.backup`,
    `prod.tfvars.json`), which reading only the last suffix let through.
    """
    name = Path(path).name
    if name.lower() in BLOCKED_NAMES:
        return name
    suffixes = Path(name).suffixes or ([name] if name.startswith(".") else [])
    lowered = [suffix.lower() for suffix in suffixes]
    if lowered and lowered[-1] in BLOCKED_SUFFIXES:
        return suffixes[-1]
    for index, suffix in enumerate(lowered[:-1]):
        if suffix not in BLOCKED_SUFFIX_FOLLOWERS:
            continue
        followers = BLOCKED_SUFFIX_FOLLOWERS[suffix]
        if followers is None or set(lowered[index + 1 :]) <= followers:
            return suffixes[index]
    return None


def check_doc_dates(revisions: GitRange) -> list[Violation]:
    violations = []
    added = set(revisions.changed_markdown(diff_filter="A"))
    for path in revisions.changed_markdown():
        changed_on = revisions.newest_author_date(path)
        added_on = revisions.added_on(path) if path in added else None
        if changed_on is None and added_on is None:
            continue
        text = revisions.read_at_head(path)
        if changed_on is not None:
            violations.append(doc_date_violation(path, text, changed_on))
        if added_on is not None:
            violations.append(created_date_violation(path, text, added_on))
    return [violation for violation in violations if violation is not None]


@dataclass(frozen=True)
class GitRange:
    """A base/head comparison in one repository, as a PR presents it."""

    repo_root: Path
    base: str
    head: str

    def changed_markdown(self, diff_filter: str = "AMR") -> list[str]:
        """Docs in scope that the range adds, modifies or renames, or those `diff_filter` picks."""
        # WHY-NOT(output): -z keeps paths as they are. Without it git C-quotes a
        # non-ASCII name, the quoted form matches no file in the log, and the doc is skipped.
        output = git(
            self.repo_root,
            "diff",
            "--name-only",
            "-z",
            "--find-renames",
            f"--diff-filter={diff_filter}",
            f"{self.base}...{self.head}",
            "--",
            "*.md",
        )
        return [path for path in output.split("\0") if path and is_doc_in_scope(path)]

    def newest_author_date(self, path: str) -> date | None:
        """The newest author date of the commits in base..head that change the doc's content.

        Author date in the author's own timezone matches the calendar day the header was
        written. A commit that only edits the metadata block or only renames the doc does not
        count. Log order follows ancestry, and a rebase can leave an older author date on top,
        so the newest date is the maximum over the range rather than the first entry.
        """
        return max(
            (
                authored_on
                for commit, authored_on in self.commits_touching(path)
                if self.changes_content(commit, path)
            ),
            default=None,
        )

    def added_on(self, path: str) -> date | None:
        """Author date of the commit in base..head that adds the doc.

        Renames are followed back to the commit that added the doc under its first name.
        Copies are not: a doc started from a copy of another is added by the copying commit.
        """
        commits = self.commits_touching(path)
        added_on = None
        while commits:
            commit, added_on = commits[-1]
            change = self.path_change(commit, path)
            if change is None or change.status != RENAMED:
                break
            path = change.source
            commits = self.commits_touching(path, until=f"{commit}^")
        return added_on

    def commits_touching(self, path: str, until: str | None = None) -> list[tuple[str, date]]:
        """Non-merge commits in base..head (or base..until) touching `path`, newest first."""
        output = git(
            self.repo_root,
            "log",
            "--no-merges",
            "--format=%H %ad",
            "--date=short",
            f"{self.base}..{until or self.head}",
            "--",
            path,
        )
        return [
            (commit, date.fromisoformat(authored_on))
            for commit, authored_on in (line.split() for line in output.splitlines())
        ]

    def changes_content(self, commit: str, path: str) -> bool:
        """Whether a non-merge commit changes the doc at `path` outside its metadata block.

        A renamed doc is compared with its path before the rename. Adding or deleting the doc
        is a content change.
        """
        change = self.path_change(commit, path)
        if change is None or change.status not in (MODIFIED, RENAMED):
            return True
        before = git(self.repo_root, "show", f"{commit}^:{change.source}")
        after = git(self.repo_root, "show", f"{commit}:{path}")
        return content_outside_metadata(before) != content_outside_metadata(after)

    def path_change(self, commit: str, path: str) -> PathChange | None:
        """How a non-merge commit changes `path`, renames detected; None if it leaves it alone."""
        raw = git(
            self.repo_root,
            "diff-tree",
            "-r",
            "-z",
            "--find-renames",
            "--root",
            "--no-commit-id",
            commit,
        )
        return path_change_in(raw, path)

    def read_at_head(self, path: str) -> str:
        return git(self.repo_root, "show", f"{self.head}:{path}")

    def committed_files(self) -> list[CommittedFile]:
        """Each file version a commit in base..head adds or modifies, with its size.

        A merge commit contributes the files that differ from every one of its parents:
        what `git add -A` swept in while the merge was in progress, and conflict resolutions.
        """
        commits = git(self.repo_root, "rev-list", f"{self.base}..{self.head}")
        changes = [
            (commit, path, blob)
            for commit in commits.split()
            for path, blob in tree_changes(
                git(
                    self.repo_root,
                    "diff-tree",
                    "-r",
                    "-c",
                    "-z",
                    "--root",
                    "--no-commit-id",
                    "--no-renames",
                    "--no-abbrev",
                    commit,
                )
            )
        ]
        sizes = blob_sizes(self.repo_root, {blob for _, _, blob in changes})
        return [CommittedFile(commit, path, sizes[blob]) for commit, path, blob in changes]

    def changed_lines(self, *pathspecs: str) -> dict[str, FileChanges]:
        """Where the diff adds, modifies or removes lines in each changed file, renames followed."""
        output = git(
            self.repo_root,
            "-c",
            "core.quotePath=false",
            "diff",
            "--unified=0",
            "--no-color",
            "--no-ext-diff",
            "--find-renames",
            "--diff-filter=AMR",
            "--src-prefix=a/",
            "--dst-prefix=b/",
            f"{self.base}...{self.head}",
            "--",
            *pathspecs,
        )
        return parse_changed_lines(output)


@dataclass
class FileChanges:
    """Where a diff touches one file, in head-side line numbers."""

    changed: set[int] = field(default_factory=set)
    """Lines added or modified."""
    deleted_after: set[int] = field(default_factory=set)
    """Lines that removed lines used to follow directly; 0 is the start of the file."""

    def touches(self, lines: Iterable[int]) -> bool:
        return not self.changed.isdisjoint(lines)

    def touches_after(self, start: int, end: int | None) -> bool:
        """Whether lines after `start`, through `end` or the end of file, were changed or removed."""
        last = sys.maxsize if end is None else end
        return any(start < line <= last for line in self.changed) or any(
            start <= line < last for line in self.deleted_after
        )


def parse_changed_lines(diff: str) -> dict[str, FileChanges]:
    """Read a `--unified=0` diff into the head-side lines each file's hunks touch."""
    files: dict[str, FileChanges] = {}
    changes = FileChanges()
    in_file_header = False
    for line in diff.split("\n"):
        if line.startswith(DIFF_FILE_HEADER):
            in_file_header = True
        elif in_file_header and line.startswith(DIFF_NEW_PATH):
            # WHY-NOT(rstrip): git ends this line with a tab when the path holds a space.
            path = line.removeprefix(DIFF_NEW_PATH).rstrip("\t")
            changes = files.setdefault(path, FileChanges())
        elif (hunk := HUNK_HEADER.match(line)) is not None:
            in_file_header = False
            start, count = int(hunk["start"]), int(hunk["count"] or 1)
            if count:
                changes.changed.update(range(start, start + count))
            else:
                changes.deleted_after.add(start)
    return files


def tree_changes(raw: str) -> list[tuple[str, str]]:
    """Read `git diff-tree -c -z` raw output into (path, new blob id).

    A record has one colon, old mode and old blob per parent, so a merge's combined record
    is wider than an ordinary one; the new mode and blob come last in their groups.
    Deletions and submodule commits are left out.
    """
    fields = raw.split("\0")
    changes = []
    for meta, path in zip(fields[0::2], fields[1::2], strict=False):
        parents = len(meta) - len(meta.lstrip(":"))
        columns = meta.lstrip(":").split()
        new_mode, new_blob = columns[parents], columns[2 * parents + 1]
        if new_mode not in (GITLINK_MODE, DELETED_MODE):
            changes.append((path, new_blob))
    return changes


def blob_sizes(repo_root: Path, blobs: set[str]) -> dict[str, int]:
    if not blobs:
        return {}
    output = git(
        repo_root,
        "cat-file",
        "--batch-check=%(objectname) %(objectsize)",
        stdin="".join(f"{blob}\n" for blob in sorted(blobs)),
    )
    return {blob: int(size) for blob, size in (line.split() for line in output.splitlines())}


def path_change_in(raw: str, path: str) -> PathChange | None:
    """Read `git diff-tree -z --find-renames` raw output for the change that leaves `path`.

    A record is the metadata (its last column the status letter plus a similarity score for
    a rename or copy), then the path, or the source and target paths for a rename or copy.
    """
    fields = raw.split("\0")
    index = 0
    while index < len(fields) - 1:
        status = fields[index].split()[-1][0]
        if status in PAIRED_STATUSES:
            source, target = fields[index + 1], fields[index + 2]
            index += 3
        else:
            source = target = fields[index + 1]
            index += 2
        if target == path:
            return PathChange(status, source)
    return None


def is_doc_in_scope(path: str) -> bool:
    """Whether the doc checks cover this Markdown path."""
    parts = PurePosixPath(path).parts
    return (
        path.endswith(".md")
        and parts[0] not in DOC_SCOPE_EXCLUDED_ROOTS
        and EXCLUDED_DIRS.isdisjoint(parts[:-1])
    )


def metadata_block(lines: list[str]) -> range | None:
    """Indexes of the metadata block: the list items of metadata keys right after the first H1.

    Both the `> - Key: value` form and legacy header lists such as `- 建立日期：...` count, as
    long as every item names a key from METADATA_KEYS or LEGACY_METADATA_KEYS; the block ends
    at the first line that is not such an item.
    """
    h1 = next((index for index, line in enumerate(lines) if ATX_H1.match(line)), None)
    if h1 is None:
        return None
    start = h1 + 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    end = start
    while end < len(lines) and is_metadata_item(lines[end]):
        end += 1
    return range(start, end) if end > start else None


def is_metadata_item(line: str) -> bool:
    match = METADATA_ITEM.match(line)
    return match is not None and match["key"].strip().casefold() in METADATA_KEY_NAMES


def content_outside_metadata(text: str) -> list[str]:
    """The doc's lines without its metadata block and the blank lines around it."""
    lines = text.splitlines()
    block = metadata_block(lines)
    if block is None:
        return lines
    before, after = lines[: block.start], lines[block.stop :]
    while before and not before[-1].strip():
        before.pop()
    while after and not after[0].strip():
        after.pop(0)
    return before + after


def doc_metadata_violations(path: str, content: str | bytes) -> list[Violation]:
    """Where a doc breaks the metadata contract in docs/reference/markdown-metadata.md."""
    if not is_doc_in_scope(path):
        return []
    try:
        text = content.decode("utf-8") if isinstance(content, bytes) else content
    except UnicodeDecodeError as error:
        line = content[: error.start].count(b"\n") + 1
        return [Violation(path, line, "not-utf8: the doc must be UTF-8 encoded")]
    lines = text.splitlines()
    if not lines or not ATX_H1.match(lines[0]):
        return [Violation(path, 1, "h1-first-line: the first line must be the doc's # H1 title")]
    block = strict_metadata_block(lines)
    if block is None:
        start = next((index for index in range(1, len(lines)) if lines[index].strip()), 0)
        message = f"metadata-block-position: {METADATA_BLOCK_EXPECTED}"
        violations = [Violation(path, start + 1, message)]
        block = range(0)
    else:
        violations = metadata_block_violations(path, lines, block)
    violations.extend(header_violations(path, lines, block))
    return sorted(violations, key=lambda violation: violation.line)


def strict_metadata_block(lines: list[str]) -> range | None:
    """Indexes of the blockquote right after the H1 on line 1, or None if another block is."""
    start = next((index for index in range(1, len(lines)) if lines[index].strip()), None)
    if start is None or not lines[start].startswith(BLOCKQUOTE):
        return None
    end = start
    while end < len(lines) and lines[end].startswith(BLOCKQUOTE):
        end += 1
    return range(start, end)


def metadata_block_violations(path: str, lines: list[str], block: range) -> list[Violation]:
    is_adr = ADR_FILE.fullmatch(path) is not None
    violations = []
    seen: dict[str, int] = {}
    dates: dict[str, date] = {}
    # WHY-NOT(named): a key on a malformed line is not reported missing as well; its
    # metadata-item violation already points at the line to fix.
    named: set[str] = set()
    for index in block:
        line = index + 1
        item = STRICT_METADATA_ITEM.match(lines[index])
        if item is None:
            violations.append(Violation(path, line, f"metadata-item: {METADATA_ITEM_FORM}"))
            loose = METADATA_ITEM.match(lines[index])
            named.update([loose["key"].strip()] if loose else [])
            continue
        key, value = item["key"], item["value"]
        named.add(key)
        problem = metadata_key_problem(key, is_adr, seen) or metadata_value_problem(
            key, value, is_adr, lines
        )
        if problem is not None:
            violations.append(Violation(path, line, problem))
            continue
        seen[key] = line
        if key in METADATA_DATE_KEYS:
            dates[key] = date.fromisoformat(value)
    if "Created" in dates and "Last Updated" in dates and dates["Last Updated"] < dates["Created"]:
        message = (
            f"date-order: 'Last Updated' must not be earlier than 'Created' ({dates['Created']})"
        )
        violations.append(Violation(path, seen["Last Updated"], message))
    required = ADR_REQUIRED_METADATA_KEYS if is_adr else REQUIRED_METADATA_KEYS
    violations.extend(
        Violation(path, block.start + 1, f"missing-key: the metadata block must have {key!r}")
        for key in required
        if key not in named
    )
    return violations


def metadata_key_problem(key: str, is_adr: bool, seen: dict[str, int]) -> str | None:
    """Why `key` cannot stand where it is, given the keys `seen` above it, or None."""
    allowed = ", ".join(METADATA_KEYS)
    if key not in METADATA_KEYS:
        return f"unknown-key: {key!r}; allowed keys: {allowed}"
    if key in ADR_ONLY_METADATA_KEYS and not is_adr:
        return f"key-not-applicable: {key!r} applies only to ADRs (docs/adr/NNNN-*.md)"
    if key in seen:
        return f"duplicate-key: {key!r} already appears on line {seen[key]}"
    later = [other for other in seen if METADATA_KEYS.index(other) > METADATA_KEYS.index(key)]
    if later:
        return f"key-order: {key!r} must come before {later[0]!r}; key order: {allowed}"
    return None


def metadata_value_problem(key: str, value: str, is_adr: bool, lines: list[str]) -> str | None:
    """Why `value` is not allowed for `key`, or None."""
    if key in METADATA_DATE_KEYS and not is_iso_date(value):
        return f"invalid-date: {key!r} must be a single YYYY-MM-DD date, got {value!r}"
    statuses = ADR_STATUSES if is_adr else DOC_STATUSES
    if key == "Status" and value not in statuses:
        kind = "an ADR" if is_adr else "a doc outside docs/adr/"
        return f"status-value: Status of {kind} must be one of {', '.join(statuses)}, got {value!r}"
    if key in LINK_METADATA_KEYS and LINK_LIST.fullmatch(value) is None:
        return (
            f"link-only: {key!r} holds only Markdown links `[text](target)` joined by `、`;"
            " move other text into the body"
        )
    if key == "Revisions" and not points_at_notes(value, lines):
        return (
            "revisions-target: 'Revisions' must be one same-file link to this ADR's Notes H2,"
            " e.g. `[Notes](#5-notes)` for `## 5. Notes`"
        )
    return None


def is_iso_date(value: str) -> bool:
    if ISO_DATE.fullmatch(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def points_at_notes(value: str, lines: list[str]) -> bool:
    link = SAME_FILE_LINK.fullmatch(value)
    notes = (match for line in lines if (match := NOTES_H2.match(line)) is not None)
    return link is not None and any(link["anchor"] == heading_anchor(h2["title"]) for h2 in notes)


def heading_anchor(title: str) -> str:
    """The fragment GitHub links a heading's text to, for plain-text headings."""
    kept = "".join(char for char in title.strip().lower() if char.isalnum() or char in " _-")
    return kept.replace(" ", "-")


def header_violations(path: str, lines: list[str], block: range) -> list[Violation]:
    """Dated lines and stray metadata keys between the H1 and the first H2, outside `block`."""
    first_h2 = next((index for index, line in enumerate(lines) if ATX_H2.match(line)), len(lines))
    violations = []
    for index in range(1, first_h2):
        if index in block:
            continue
        text = HEADER_LINE_PREFIX.sub("", lines[index])
        key = HEADER_KEY.match(text)
        if ISO_DATE.match(text) or text.startswith(REVISION_WORD):
            message = (
                "header-dated-line: lines starting with a date or 修訂 do not belong in the"
                " header; leave the change log to commit messages and ADR Notes"
            )
            violations.append(Violation(path, index + 1, message))
        elif key is not None and key["key"].strip().casefold() in METADATA_KEY_NAMES:
            message = (
                f"header-stray-key: {key['key'].strip()!r} belongs in the metadata block as"
                f" `> - Key: value` with one of: {', '.join(METADATA_KEYS)}"
            )
            violations.append(Violation(path, index + 1, message))
    return violations


def doc_date_violation(path: str, text: str, changed_on: date) -> Violation | None:
    if not is_doc_in_scope(path):
        return None
    header = find_last_updated(text)
    if header is None:
        return Violation(path, 1, "missing last-updated header")
    try:
        updated_on = header.value
    except ValueError:
        return Violation(path, header.line, f"invalid last-updated date {header.raw!r}")
    if updated_on >= changed_on:
        return None
    return Violation(
        path,
        header.line,
        f"last-updated date {updated_on} is older than this change ({changed_on}); update the header",
    )


def created_date_violation(path: str, text: str, added_on: date) -> Violation | None:
    """A doc's created date must not predate the commit that adds it; a missing one passes here."""
    header = find_header_date(CREATED, text)
    if not is_doc_in_scope(path) or header is None:
        return None
    try:
        created_on = header.value
    except ValueError:
        return Violation(path, header.line, f"invalid created date {header.raw!r}")
    if created_on >= added_on:
        return None
    return Violation(
        path,
        header.line,
        f"created date {created_on} is older than the commit that adds this doc ({added_on});"
        " set it to the day the doc was added",
    )


def find_last_updated(text: str) -> HeaderDate | None:
    return find_header_date(LAST_UPDATED, text)


def find_header_date(header: re.Pattern[str], text: str) -> HeaderDate | None:
    for number, line in enumerate(text.splitlines(), start=1):
        match = header.match(line)
        if match is not None:
            return HeaderDate(number, match["value"])
    return None


@dataclass(frozen=True)
class Comment:
    """A `#` comment found by tokenize, so `#` inside string literals is never one."""

    line: int
    column: int
    text: str
    full_line: bool

    @property
    def body(self) -> str:
        """The comment text after `#` and the spaces that follow it."""
        return self.text[1:].strip()


def python_comments(source: str) -> Iterator[Comment]:
    """Yield every comment in Python source in order; raise ValueError if it cannot tokenize."""
    for token in python_tokens(source):
        if token.type == tokenize.COMMENT:
            line, column = token.start
            full_line = not token.line[:column].strip()
            yield Comment(line, column, token.string, full_line)


@dataclass(frozen=True)
class CodeToken:
    line: int
    text: str
    is_name: bool


@dataclass(frozen=True)
class LogicalLine:
    """One statement as tokenize ends it at NEWLINE, however many physical lines it spans."""

    tokens: tuple[CodeToken, ...]

    @property
    def first(self) -> int:
        return self.tokens[0].line

    @property
    def is_decorator(self) -> bool:
        return self.tokens[0].text == DECORATOR

    def ends_after(self, line: int) -> bool:
        return self.tokens[-1].line > line

    def tokens_after(self, line: int) -> tuple[CodeToken, ...]:
        return tuple(token for token in self.tokens if token.line > line)


def logical_lines(source: str) -> list[LogicalLine]:
    """Split Python source into logical lines of code tokens; comments and blank lines drop out."""
    lines: list[LogicalLine] = []
    tokens: list[CodeToken] = []
    for token in python_tokens(source):
        if token.type == tokenize.NEWLINE:
            if tokens:
                lines.append(LogicalLine(tuple(tokens)))
            tokens = []
        elif token.type not in NON_CODE_TOKENS:
            tokens.append(CodeToken(token.start[0], token.string, token.type == tokenize.NAME))
    return lines


def python_tokens(source: str) -> Iterator[tokenize.TokenInfo]:
    readline = iter(source.splitlines(keepends=True)).__next__
    try:
        yield from tokenize.generate_tokens(readline)
    except (tokenize.TokenError, SyntaxError) as error:
        raise ValueError(f"cannot tokenize Python source: {error}") from error


def git(repo_root: Path, *args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=stdin,
    )
    return result.stdout


def relative(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
