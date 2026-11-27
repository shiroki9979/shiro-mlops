# Domain Docs

> - Created: 2026-08-25
> - Last Updated: 2026-11-27

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root, or
- **`GLOSSARY-MAP.md`** at the repo root if it exists: it points at one `GLOSSARY.md` per context. Read each one relevant to the topic.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in. In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo (most repos):

```text
/
├── GLOSSARY.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

Multi-context repo (presence of `GLOSSARY-MAP.md` at the root):

```text
/
├── GLOSSARY-MAP.md
├── docs/adr/                          ← system-wide decisions
└── src/
    ├── ordering/
    │   ├── GLOSSARY.md
    │   └── docs/adr/                  ← context-specific decisions
    └── billing/
        ├── GLOSSARY.md
        └── docs/adr/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Name terms against industry vocabulary

When adding or renaming a glossary term, the canonical name is the 繁體中文 domain term with its English name in parentheses. Industry vocabulary (MLflow alias, champion/challenger, promotion, model validation, …) is a cross-reference, never the canonical name.

- **Keep the existing name** unless one of two things holds: an industry term of the same name draws a different concept boundary, so outside readers would misread it; or two concepts inside the repo share a name. Only then propose a rename.
- **Different boundary**: list the industry term under the entry's `_Avoid_`, as `評估閘門` does with champion/challenger.
- **Same boundary**: the industry term may serve as the entry's English name or be recorded as a cross-reference; it still doesn't replace the 繁體中文 name.
- **Banned terms**: only retired repo terms go into `BANNED_TERMS` in `scripts/check_conventions.py`; industry terms never do, because they legitimately appear as cross-references. The `terms` check skips the places that must spell out a retired term: GLOSSARY lines starting with `_Avoid_`, and Markdown under `docs/research/`.

The term-by-term mapping lives in [the ML governance terminology research](../research/2026-11-27-ml-governance-terminology.md).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_
