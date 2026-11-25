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
from typing import NamedTuple

SAFE_ACTIONS = frozenset({"no-op", "create", "read", "update"})
REPLACE_LABELS: dict[tuple[str, ...], str] = {
    ("delete", "create"): "replace (delete, then create)",
    ("create", "delete"): "replace (create, then delete)",
}


class ResourceChange(NamedTuple):
    address: str
    actions: tuple[str, ...]

    @property
    def is_safe(self) -> bool:
        return set(self.actions) <= SAFE_ACTIONS

    @property
    def display_action(self) -> str:
        return REPLACE_LABELS.get(self.actions, "+".join(self.actions))


def find_violations(changes: list[ResourceChange]) -> list[ResourceChange]:
    return [change for change in changes if not change.is_safe]


def render_summary(changes: list[ResourceChange], violations: list[ResourceChange]) -> str:
    by_label: dict[str, list[str]] = {}
    for change in changes:
        by_label.setdefault(change.display_action, []).append(change.address)

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
        lines += [f"- `{change.address}`: {change.display_action}" for change in violations]
        lines.append("")
    else:
        lines += ["**Result: safe**", ""]
    lines += ["| Action | Count |", "| :--- | ---: |"]
    lines += [f"| {label} | {len(addresses)} |" for label, addresses in by_label.items()]
    for label, addresses in by_label.items():
        lines += ["", f"### {label} ({len(addresses)})", ""]
        lines += [f"- `{address}`" for address in addresses]
    return "\n".join(lines) + "\n"


class InvalidPlanError(Exception):
    """The input cannot be judged; the message is the reason shown to the caller."""


def load_changes(path: Path) -> list[ResourceChange]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise InvalidPlanError(f"cannot read {path}: {error}") from error
    try:
        plan = json.loads(text)
    except ValueError as error:
        raise InvalidPlanError(f"{path} is not valid JSON: {error}") from error
    try:
        # WHY-NOT(resource_changes): Terraform omits the key when the configuration has no
        # resources, so indexing it instead of `.get` would reject an empty plan as invalid.
        resource_changes = plan.get("resource_changes", [])
        return [
            ResourceChange(
                str(change["address"]), tuple(str(action) for action in change["change"]["actions"])
            )
            for change in resource_changes
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

    violations = find_violations(changes)
    print(render_summary(changes, violations), end="")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
