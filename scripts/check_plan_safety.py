"""Decide whether CI may apply a saved Terraform plan, and summarise it as Markdown.

Input is the output of `terraform show -json <saved plan>`.
Exit code: 0 when the plan is safe, 1 when it is not, 2 for invalid arguments or JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

SAFE_ACTIONS = frozenset({"no-op", "create", "read", "update"})
REPLACE_LABELS = {
    ("delete", "create"): "replace (delete, then create)",
    ("create", "delete"): "replace (create, then delete)",
}


def is_safe(actions: tuple[str, ...]) -> bool:
    return set(actions) <= SAFE_ACTIONS


def label(actions: tuple[str, ...]) -> str:
    return REPLACE_LABELS.get(actions, "+".join(actions))


def render_summary(changes: list[tuple[str, tuple[str, ...]]]) -> str:
    by_action: dict[str, list[str]] = {}
    for address, actions in changes:
        by_action.setdefault(label(actions), []).append(address)
    violations = [(address, actions) for address, actions in changes if not is_safe(actions)]

    lines = ["## Terraform plan safety check", ""]
    if violations:
        lines += [
            f"**Result: unsafe**: {len(violations)} resource change(s) delete, replace or forget"
            " a resource. CI does not apply such a plan; it must be applied by a person on a"
            " local machine.",
            "",
            "### Violations",
            "",
        ]
        lines += [f"- `{address}`: {label(actions)}" for address, actions in violations]
        lines.append("")
    else:
        lines += ["**Result: safe**", ""]
    lines += ["| Action | Count |", "| :--- | ---: |"]
    lines += [f"| {action} | {len(addresses)} |" for action, addresses in by_action.items()]
    for action, addresses in by_action.items():
        lines += ["", f"### {action} ({len(addresses)})", ""]
        lines += [f"- `{address}`" for address in addresses]
    return "\n".join(lines) + "\n"


class InvalidPlanError(Exception):
    """The input cannot be judged; the message is the reason shown to the caller."""


def load_changes(path: Path) -> list[tuple[str, tuple[str, ...]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise InvalidPlanError(f"cannot read {path}: {error}") from error
    try:
        plan = json.loads(text)
    except ValueError as error:
        raise InvalidPlanError(f"{path} is not valid JSON: {error}") from error
    try:
        # Terraform omits `resource_changes` when the configuration has no resources.
        return [
            (str(change["address"]), tuple(str(action) for action in change["change"]["actions"]))
            for change in plan.get("resource_changes", [])
        ]
    except (AttributeError, KeyError, TypeError) as error:
        raise InvalidPlanError(
            f"{path} is not a `terraform show -json` plan: missing or malformed {error}"
        ) from error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan_json", type=Path, help="output of `terraform show -json`")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0)
    try:
        changes = load_changes(args.plan_json)
    except InvalidPlanError as error:
        print(f"plan safety check: {error}", file=sys.stderr)
        return 2

    print(render_summary(changes), end="")
    return 0 if all(is_safe(actions) for _, actions in changes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
