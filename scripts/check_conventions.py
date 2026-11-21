"""Check repository conventions that are mechanical enough to enforce in CI.

Checks:
  python-uv  Makefile recipes and CI `run:` commands must not start with a host python/python3.
  terms      Tracked Markdown must not use banned terms; the preferred term is reported.
  doc-dates  Docs changed between --base and --head must carry a last-updated header dated no
             earlier than the newest author date of their commits in that range.
  debt-markers
             TODO/FIXME/HACK/XXX in tracked source files must name their tech-debt issue,
             as in `TODO(#123): ...` (see docs/agents/tech-debt.md).
  comment-refs
             Paths starting with a tracked top-level directory and ADR-NNNN numbers in tracked
             Python comments must exist; paths with glob or placeholder characters are skipped.
  comment-kinds
             Comment blocks in src/ and scripts/ Python files that --base..--head adds or modifies
             must start with WHY-NOT(<name>): <reason>, SYNC(<path>[, <path>...]): <note>,
             TODO(#<issue>), or a tool directive; noqa and type: ignore need a reason.
             A WHY-NOT name (its last dotted part) must be an identifier on the next logical
             line after the block, or on the comment's own logical line for a trailing comment.
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
import tokenize
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = "Makefile"
WORKFLOW_GLOB = ".github/workflows/*.yml"
EXCLUDED_DIRS = frozenset({"node_modules", ".venv"})
DOC_DATES_EXCLUDED_DIRS = frozenset({"lab"})
COMMENT_KINDS_DIRS = ("src", "scripts")
DIFF_CHECKS = ("doc-dates", "comment-kinds")

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

# WHY-NOT(PATH_CANDIDATE): glob and placeholder characters continue the match instead of ending
# it, so a pattern is skipped whole rather than cut down to a concrete-looking directory.
PATH_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9_./${}<>*?\[\]-])(?P<path>[A-Za-z0-9_.-]+/[A-Za-z0-9_./${}<>*?\[\]-]*)"
)
# WHY-NOT(PATH_PATTERN_CHARS): a path holding any of these is an illustrative pattern, not one
# concrete file, so it is skipped rather than resolved.
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
TODO_WITH_ISSUE = re.compile(r"TODO\(#\d+\)")
SUPPRESSION = re.compile(
    r"(?P<directive>noqa(?::\s*[A-Z]+[0-9]+(?:\s*,\s*[A-Z]+[0-9]+)*)?|type:\s*ignore(?:\[[^\]]*\])?)"
    r"(?P<reason>.*)"
)
REASON_SEPARATORS = " \t-:;,\u2013\u2014"
TOOL_DIRECTIVE = re.compile(r"(?:pragma\b|fmt:|ruff:)")
ALLOWED_COMMENT_KINDS = (
    "WHY-NOT(<name>): <reason>, SYNC(<path>[, <path>...]): <note>, TODO(#<issue>), "
    "or a tool directive (noqa or type: ignore followed by a reason, pragma, fmt:, ruff:)"
)
HUNK_HEADER = re.compile(r"@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")
DIFF_FILE_HEADER = "diff --git "
DIFF_NEW_PATH = "+++ b/"

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
    "comment-refs": lambda args: check_comment_refs(REPO_ROOT),
    "comment-kinds": lambda args: check_comment_kinds(GitRange(REPO_ROOT, args.base, args.head)),
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
    parser.add_argument(
        "--base", help="base ref for doc-dates and comment-kinds, e.g. origin/dev or a PR base SHA"
    )
    parser.add_argument(
        "--head", default="HEAD", help="head ref for doc-dates and comment-kinds (default: HEAD)"
    )
    args = parser.parse_args(argv)
    for name in DIFF_CHECKS:
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
        for comment in file_comments(repo_root, path)
        for message in comment_ref_problems(comment.text, tree, adrs)
    ]


def file_comments(repo_root: Path, path: str) -> list[Comment]:
    return source_comments(path, (repo_root / path).read_text(encoding="utf-8"))


def source_comments(path: str, source: str) -> list[Comment]:
    try:
        return list(python_comments(source))
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error


def comment_ref_problems(text: str, tree: TrackedTree, adrs: set[str]) -> list[str]:
    problems = [
        f"comment refers to missing path '{ref}'"
        for ref in find_path_refs(text, tree.top_level_dirs)
        if not tree.contains(ref)
    ]
    problems += [
        f"comment refers to {match[0]}, but docs/adr/ has no {match['number']}-*.md"
        for match in ADR_REF.finditer(text)
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
        for path, added in revisions.added_lines(*COMMENT_KINDS_DIRS).items()
        if is_comment_kinds_source(path)
        for violation in comment_kind_violations(path, revisions.read_at_head(path), added)
    ]


def is_comment_kinds_source(path: str) -> bool:
    return path.endswith(".py") and Path(path).parts[0] in COMMENT_KINDS_DIRS


def comment_kind_violations(path: str, source: str, added: set[int]) -> list[Violation]:
    """Check each comment block of `source` that has a line among the `added` line numbers."""
    blocks = comment_blocks(source_comments(path, source))
    code = logical_lines(source)
    return [
        Violation(path, block.first.line, problem)
        for block in blocks
        if block.lines & added
        for problem in [comment_kind_problem(block) or why_not_anchor_problem(block, code)]
        if problem is not None
    ]


@dataclass(frozen=True)
class CommentBlock:
    """Comments read as one unit; only the first one carries the kind tag."""

    comments: tuple[Comment, ...]

    @property
    def first(self) -> Comment:
        return self.comments[0]

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
    )


def comment_kind_problem(block: CommentBlock) -> str | None:
    body = block.first.body
    if body.startswith(WHY_NOT_TAG):
        if WHY_NOT.match(body):
            return None
        return "WHY-NOT comment must read `WHY-NOT(<name>): <reason>`, naming the code it protects"
    if body.startswith(SYNC_TAG):
        if SYNC.match(body):
            return None
        return "SYNC comment must read `SYNC(<path>[, <path>...]): <note>` with repo-rooted paths"
    if TODO_WITH_ISSUE.match(body) or TOOL_DIRECTIVE.match(body):
        return None
    suppression = SUPPRESSION.match(body)
    if suppression is not None:
        if suppression["reason"].strip(REASON_SEPARATORS):
            return None
        directive = suppression["directive"]
        return f"`{directive}` needs a reason after it, e.g. `# {directive} — <why it is needed>`"
    return (
        f"comment block does not start with an allowed kind ({ALLOWED_COMMENT_KINDS}); "
        "tag its first line with one of them, or delete the comment if the code already says it "
        "(see CODING_STANDARDS.md, 程式碼註解)"
    )


def why_not_anchor_problem(block: CommentBlock, code: list[LogicalLine]) -> str | None:
    """Require the WHY-NOT name on the code the block protects; dotted names match their last part."""
    match = WHY_NOT.match(block.first.body)
    if match is None:
        return None
    name = match["name"].rpartition(".")[2]
    if block.first.full_line:
        end = max(block.lines)
        tokens = next((line.tokens_after(end) for line in code if line.ends_after(end)), ())
        where = (
            f"the next logical line (line {tokens[0].line})"
            if tokens
            else "the next logical line, but no code follows the comment"
        )
    else:
        tokens = next(
            (line.tokens for line in reversed(code) if line.first <= block.first.line), ()
        )
        where = f"the same logical line (line {block.first.line})"
    if any(token.is_name and token.text == name for token in tokens):
        return None
    named = f"'{name}'" if name == match["name"] else f"'{name}' (from '{match['name']}')"
    return (
        f"WHY-NOT name {named} must appear on {where}; anchor the comment on the code it "
        "protects, or update or delete it if that code was renamed or removed"
    )


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

    def added_lines(self, *pathspecs: str) -> dict[str, set[int]]:
        """Head-side line numbers added or modified in each changed file, renames followed."""
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
        return parse_added_lines(output)


def parse_added_lines(diff: str) -> dict[str, set[int]]:
    added: dict[str, set[int]] = {}
    lines: set[int] = set()
    in_file_header = False
    for line in diff.split("\n"):
        if line.startswith(DIFF_FILE_HEADER):
            in_file_header = True
        elif in_file_header and line.startswith(DIFF_NEW_PATH):
            lines = added.setdefault(line.removeprefix(DIFF_NEW_PATH), set())
        elif (hunk := HUNK_HEADER.match(line)) is not None:
            in_file_header = False
            start = int(hunk["start"])
            lines.update(range(start, start + int(hunk["count"] or 1)))
    return added


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


def git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return result.stdout


def relative(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
