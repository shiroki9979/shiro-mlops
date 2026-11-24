# Triage Labels

> - Created: 2026-08-25
> - Last Updated: 2026-11-20

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the "Label in our tracker" column to match whatever vocabulary you actually use.

## Category labels

Category labels describe what an issue is, not where it is in triage, and combine with any role above.

| Label            | Meaning                                                                                                                                          |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `tech-debt`      | A known shortcut or gap with an ongoing cost; see [tech-debt.md](tech-debt.md)                                                                   |
| `ops-acceptance` | Proves a milestone with production data in the running environment; closed once the evidence is posted. See [issue-tracker.md](issue-tracker.md) |
