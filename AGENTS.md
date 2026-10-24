# AGENTS.md

Welcome to `shiro-mlops`. This repository is a hybrid Local/AWS MLOps platform for dynamic horizon power load forecasting.

## Essential Context Pointers

- **Domain Glossary & Semantics**: Read [CONTEXT.md](CONTEXT.md) for business context, power grid terminology, and degraded forecast definitions.
- **System & Data Specifications**: Read [docs/SPEC.md](docs/SPEC.md) for schemas, Feast FeatureViews, REST contracts, and Dagster jobs.
- **Architecture Decisions**: Consult [docs/adr/](docs/adr/) for rationale behind hybrid topology, Feast storage, LightGBM recursive forecaster, Dagster SDA, TimescaleDB, `uv`, CWA ingestion isolation, derived hourly actual load, ML task decoupling (task config + task types), and native model persistence.
- **Roadmap & Work Tickets**: Consult [docs/ROADMAP.md](docs/ROADMAP.md) for tracer-bullet tickets and milestone acceptance criteria.
- **Operational Guides**:
  - Tutorial: [docs/tutorials/quickstart-local-prediction.md](docs/tutorials/quickstart-local-prediction.md)
  - Full Local Stack: [docs/how-to/run-full-local-stack.md](docs/how-to/run-full-local-stack.md)
  - AWS Deployment: [docs/how-to/deploy-aws-infrastructure.md](docs/how-to/deploy-aws-infrastructure.md)

## Development Loop & Commands

Always use `uv` for Python virtual environment and dependency management:

```bash
# Sync dependencies
uv sync --all-extras

# Run test suite (100% mocked offline tests, fast execution)
uv run pytest tests/ -v

# Lint & formatting checks
uv run ruff check .
uv run ruff format --check .

# Local API dev server
uv run uvicorn shiro_mlops.service.api:app --host 0.0.0.0 --port 8000
```

## Engineering Principles for Agents

1. **Red-Green-Refactor**: Always write or update tests before or alongside code changes.
2. **Offline Unit/Integration Tests**: Tests in `tests/` must NOT depend on external live APIs; use fixtures in `tests/fixtures/`.
3. **No Implementation Details in CONTEXT.md**: `CONTEXT.md` is strictly reserved for business domain terms. Technical details belong in `docs/SPEC.md` or `docs/adr/`.
4. **Diátaxis Discipline**: When adding docs, adhere strictly to the 4 quadrants (Tutorial, How-To, Reference, Explanation).

## Agent skills

### Issue tracker & PR base branch

GitHub issues via `gh` CLI. Feature/fix PRs use base `dev` (`gh pr create --base dev`); `main` receives only `dev` release merges. See [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md).

### Triage labels

Canonical five-role triage vocabulary. See [docs/agents/triage-labels.md](docs/agents/triage-labels.md).

### Domain docs

Single-context layout (`CONTEXT.md` + `docs/adr/`). See [docs/agents/domain.md](docs/agents/domain.md).
