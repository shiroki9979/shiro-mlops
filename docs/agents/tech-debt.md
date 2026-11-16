# Tech Debt

- 建立日期：2026-11-16
- 最後更新：2026-11-16

How this repo records, triages, and pays down tech debt. The registry is the GitHub issue tracker (see [issue-tracker.md](issue-tracker.md)); there is no separate Markdown list to drift out of date.

## What counts as tech debt

Tech debt is a known shortcut or gap in code, infrastructure, or tooling that we chose to keep, and that keeps costing something until it is fixed: slower changes, duplicated rules, operational risk, or a check we cannot run.

It is **not**:

- A missing feature or milestone gap: that belongs in [ROADMAP.md](../ROADMAP.md) or a feature issue.
- A bug (behaviour differs from the spec): open a bug issue.
- An ADR "Out of Scope / Deferred" item that costs nothing while it stays undone, such as a capability nobody needs yet. Only deferred items with an ongoing cost are debt.

## Recording debt

Every debt item is one GitHub issue labelled `tech-debt`. Open it at the moment the debt is accepted:

- **In a PR**: when a change knowingly takes a shortcut, open the issue before merging and link it from the PR description.
- **In an ADR**: when a Deferred item or a Consequence carries an ongoing cost, link the issue next to it.
- **In an architecture review**: candidates that are not taken now become issues, with the review's suggested timing as the trigger.
- **In code**: a `TODO`, `FIXME`, `HACK`, or `XXX` comment must name its issue directly after the marker, as in `TODO(#123): ...`. CI enforces this with `scripts/check_conventions.py debt-markers`; Markdown, JSON fixtures, and lockfiles are not scanned.

Issue body:

```markdown
## Current state
What the shortcut or gap is, with file or ADR links.

## Cost
What it costs while it stays: which changes it slows, which risk it leaves open.

## Payoff
What fixing it involves, and roughly how large it is.

## Trigger
The concrete condition that makes it worth paying now, e.g. "next change to weather version selection".

## Source
The PR, ADR, or review that accepted the debt.
```

## Triage

`tech-debt` is a category label, not a triage role. It sits alongside the roles in [triage-labels.md](triage-labels.md): a new debt issue starts at `needs-triage` and moves to `ready-for-agent`, `ready-for-human`, or `wontfix` like any other issue. Close as `wontfix` when the cost no longer exists, for example because the code was removed.

Priority comes from the **Trigger**, not from a separate priority label: debt is paid when its trigger fires, or earlier if the cost grows.

## Paying debt down

- Before changing an area, search open `tech-debt` issues for it (`gh issue list --label tech-debt --state open`). If its trigger has fired, pay it in the same PR when the change stays small; otherwise open a dedicated PR.
- Close the issue with `Closes #<n>` in the PR that pays it, and in that PR remove every `(#<n>)` marker in code and update the ADR or review that linked it.
