"""Check repository conventions that are mechanical enough to enforce in CI.

Checks:
  python-uv  Makefile recipes and CI `run:` commands must not start with a host python/python3.
  terms      Tracked Markdown must not use banned terms; the preferred term is reported.
  doc-dates  Docs changed between --base and --head must carry a last-updated header dated no
             earlier than the newest author date of their commits in that range.
  debt-markers
             TODO/FIXME/HACK/XXX in tracked source files must name their tech-debt issue,
             as in `TODO(#123): ...` (see docs/agents/tech-debt.md).
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = "Makefile"
WORKFLOW_GLOB = ".github/workflows/*.yml"
EXCLUDED_DIRS = frozenset({"node_modules", ".venv"})
DOC_DATES_EXCLUDED_DIRS = frozenset({"lab"})

# Single source for terminology: banned term -> preferred replacement.
BANNED_TERMS = {
    "端口": "連接埠",
}

HOST_PYTHON = re.compile(r"(?:.*/)?python(?:3(?:\.\d+)?)?")
ENV_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
COMMAND_SEPARATORS = frozenset({";", ";;", "&", "&&", "|", "||", "|&", "("})
# Shell reserved words are syntax, so the word after them is still the command word.
RESERVED_WORDS = frozenset({"!", "{", "if", "then", "elif", "else", "while", "until", "do", "time"})
MAKE_RECIPE_PREFIXES = "@-+"
LINE_CONTINUATION = "\\"

RUN_KEY = re.compile(r"^(?P<indent>\s*)(?:-\s+)?run:\s*(?P<value>.*)$")
BLOCK_SCALAR = re.compile(r"^(?P<style>[|>])[-+0-9]*\s*(?:#.*)?$")
FOLDED_STYLE = ">"
YAML_QUOTES = "\"'"

DEBT_MARKER = re.compile(r"\b(?P<marker>TODO|FIXME|HACK|XXX)\b(?!\(#\d+\))")
DEBT_MARKER_SUFFIXES = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".sh", ".sql", ".css", ".html", ".conf"}
    | {".toml", ".yml", ".yaml", ".tf"}
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

LAST_UPDATED = re.compile(
    r"^\s*(?:[>*-]\s+)*(?:\*\*)?(?:最後更新|Last Updated)(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*"
    r"(?P<value>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)


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


# Check name -> runner; the single list of checks the CLI accepts.
CHECKS: dict[str, Callable[[argparse.Namespace], list[Violation]]] = {
    "python-uv": lambda args: check_python_uv(REPO_ROOT),
    "terms": lambda args: check_terms(REPO_ROOT),
    "doc-dates": lambda args: check_doc_dates(GitRange(REPO_ROOT, args.base, args.head)),
    "debt-markers": lambda args: check_debt_markers(REPO_ROOT),
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
    parser.add_argument("--base", help="base ref for doc-dates, e.g. origin/dev or a PR base SHA")
    parser.add_argument("--head", default="HEAD", help="head ref for doc-dates (default: HEAD)")
    args = parser.parse_args(argv)
    if "doc-dates" in args.checks and not args.base:
        parser.error("doc-dates requires --base")
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


# --- python-uv -------------------------------------------------------------


def check_python_uv(repo_root: Path) -> list[Violation]:
    sources: list[tuple[Path, Callable[[str], list[SourceLine]]]] = [
        (repo_root / MAKEFILE, find_host_python_in_makefile)
    ]
    sources += [
        (path, find_host_python_in_workflow) for path in sorted(repo_root.glob(WORKFLOW_GLOB))
    ]
    return [
        violation
        for path, find in sources
        for violation in host_python_violations(relative(path, repo_root), path, find)
    ]


def host_python_violations(
    label: str, path: Path, find: Callable[[str], list[SourceLine]]
) -> list[Violation]:
    try:
        commands = find(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ValueError(f"{label}: {error}") from error
    return [Violation(label, command.line, host_python_message(command)) for command in commands]


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
        scalar = BLOCK_SCALAR.match(value)
        if scalar is not None:
            blocks.append(block_scalar(lines, index, len(match["indent"]), scalar["style"]))
        elif value:
            blocks.append([SourceLine(index + 1, unquote_yaml(value))])
    return blocks


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
    tokens = shell_tokens(command.text)
    if tokens is None:
        raise ValueError(f"line {command.line}: cannot parse shell command {command.text!r}")
    return any(HOST_PYTHON.fullmatch(word) for word in command_words(tokens))


def command_words(tokens: list[str]) -> list[str]:
    words = []
    at_command_start = True
    for token in tokens:
        if token in COMMAND_SEPARATORS:
            at_command_start = True
        elif at_command_start and (token in RESERVED_WORDS or ENV_ASSIGNMENT.match(token)):
            continue
        elif at_command_start:
            words.append(token)
            at_command_start = False
    return words


# --- terms -----------------------------------------------------------------


def check_terms(repo_root: Path) -> list[Violation]:
    return [
        Violation(path, hit.line, f"banned term '{hit.term}'; use '{hit.replacement}'")
        for path in tracked_markdown(repo_root)
        for hit in find_banned_terms((repo_root / path).read_text(encoding="utf-8"))
    ]


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


# --- debt-markers ----------------------------------------------------------


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


# --- doc-dates -------------------------------------------------------------


def check_doc_dates(revisions: GitRange) -> list[Violation]:
    violations = []
    for path in revisions.changed_markdown():
        changed_on = revisions.newest_author_date(path)
        if changed_on is None:
            continue
        violation = doc_date_violation(path, revisions.read_at_head(path), changed_on)
        if violation is not None:
            violations.append(violation)
    return violations


@dataclass(frozen=True)
class GitRange:
    """A base/head comparison in one repository, as a PR presents it."""

    repo_root: Path
    base: str
    head: str

    def changed_markdown(self) -> list[str]:
        output = git(
            self.repo_root,
            "diff",
            "--name-only",
            "--diff-filter=AMR",
            f"{self.base}...{self.head}",
            "--",
            "*.md",
        )
        return [path for path in output.splitlines() if path and not is_doc_date_excluded(path)]

    def newest_author_date(self, path: str) -> date | None:
        # Author date in the author's own timezone matches the calendar day the header was written.
        # Log order follows ancestry, and a rebase can leave an older author date on top, so the
        # newest date is the maximum over the range rather than the first entry.
        output = git(
            self.repo_root,
            "log",
            "--no-merges",
            "--format=%ad",
            "--date=short",
            f"{self.base}..{self.head}",
            "--",
            path,
        )
        return max(map(date.fromisoformat, output.split()), default=None)

    def read_at_head(self, path: str) -> str:
        return git(self.repo_root, "show", f"{self.head}:{path}")


def is_doc_date_excluded(path: str) -> bool:
    return bool(DOC_DATES_EXCLUDED_DIRS.intersection(Path(path).parts[:1]))


def doc_date_violation(path: str, text: str, changed_on: date) -> Violation | None:
    if is_doc_date_excluded(path):
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


def find_last_updated(text: str) -> HeaderDate | None:
    for number, line in enumerate(text.splitlines(), start=1):
        match = LAST_UPDATED.match(line)
        if match is not None:
            return HeaderDate(number, match["value"])
    return None


# --- shared ----------------------------------------------------------------


def git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return result.stdout


def relative(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
