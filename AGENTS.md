# AGENTS.md

- Created: 2026-08-23
- Last updated: 2026-11-21

Welcome to `shiro-mlops`. This repository is a hybrid Local/AWS MLOps platform for dynamic horizon power load forecasting.

## Essential Context Pointers

- **Domain Glossary & Semantics**: Read [GLOSSARY.md](GLOSSARY.md) for business context, power grid terminology, and degraded forecast definitions.
- **System & Data Specifications**: `docs/reference/` holds the current contracts, one file per area; edit them in the same PR as the code they describe.
  - [data-contracts.md](docs/reference/data-contracts.md): source schemas, TimescaleDB hypertables, Feast FeatureViews, artifact serialization.
  - [rest-api.md](docs/reference/rest-api.md): REST contracts.
  - [dagster-schedules.md](docs/reference/dagster-schedules.md): Dagster assets, jobs, schedules, minimum accumulation.
  - [data-explorer.md](docs/reference/data-explorer.md): Data Explorer boundaries and query behaviour.
  - [ml-tasks.md](docs/reference/ml-tasks.md): task config schema, task types, runner, model store.
  - [frontend-locale.md](docs/reference/frontend-locale.md): frontend locale and formatting.
  - [lab.md](docs/reference/lab.md): `lab/` snapshot, backtest and report contracts.
  - [forecast-view-hosting.md](docs/reference/forecast-view-hosting.md): S3 + CloudFront hosting of the Forecast View.
  - [terraform-state-and-deployment.md](docs/reference/terraform-state-and-deployment.md): the two Terraform layers, S3 remote state and locking, and the GitHub OIDC roles' trust and permissions.
- **Architecture Decisions**: Consult [docs/adr/](docs/adr/) for rationale behind hybrid topology, Feast storage, LightGBM recursive forecaster, Dagster SDA, TimescaleDB, `uv`, CWA ingestion isolation, derived hourly actual load, ML task decoupling (task config + task types), native model persistence, the co-located `lab/` research workspace ([ADR-0011](docs/adr/0011-co-locate-lab-workspace-with-unidirectional-dependency.md)), and the static, precomputed Forecast View as the only cloud surface ([ADR-0015](docs/adr/0015-publish-forecast-view-as-static-precomputed-output.md), superseding ADR-0001).
- **Research Workspace (`lab/`)**: `lab/` is a `uv` workspace member that depends unidirectionally on `shiro_mlops` (`src/` must NEVER import `lab`). Use it to freeze point-in-time training table snapshots, run rolling-origin backtests (滾動起點回測), and record hyperparameter studies under `lab/<YYYY-MM-DD>-<topic>/`.
- **Roadmap & Work Tickets**: [docs/ROADMAP.md](docs/ROADMAP.md) indexes milestones (goals, acceptance criteria, priority). Work tickets, their Definition of Done and status live in GitHub issues; operational acceptance has its own `ops-acceptance` issues. See [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md).
- **Code Review Standards**: When reviewing a change, apply [CODING_STANDARDS.md](CODING_STANDARDS.md) for repo-specific judgement rules; mechanical rules run in CI.
- **Operational Guides**:
  - Tutorial: [docs/tutorials/quickstart-local-prediction.md](docs/tutorials/quickstart-local-prediction.md)
  - Full Local Stack: [docs/how-to/run-full-local-stack.md](docs/how-to/run-full-local-stack.md)
  - Lab Research Study: [docs/how-to/run-lab-study.md](docs/how-to/run-lab-study.md)
  - AWS Deployment: [docs/how-to/deploy-aws-infrastructure.md](docs/how-to/deploy-aws-infrastructure.md)

## Development Loop & Commands

Always use `uv` for Python virtual environment and dependency management:

```bash
# Sync dependencies
uv sync --all-extras

# Run test suite (100% mocked offline tests, fast execution)
uv run pytest tests/ -v

# Sync and test the lab research workspace
uv sync --package lab
uv run --package lab pytest lab/tests -v

# Freeze an immutable training table snapshot for lab research
uv run --package lab python -m lab.snapshot dynamic_horizon_forecast --as-of 2026-11-08T22:00:00

# Lint & formatting checks
uv run ruff check .
uv run ruff format --check .

# Repository convention & Markdown checks (also run in CI)
uv run python scripts/check_conventions.py python-uv docker-pins terms debt-markers comment-refs doc-dates comment-kinds --base origin/dev
npx markdownlint-cli2 "**/*.md"

# Local API dev server
uv run uvicorn shiro_mlops.service.api:app --host 0.0.0.0 --port 8000
```

## Engineering Principles for Agents

1. **Red-Green-Refactor**: Always write or update tests before or alongside code changes.
2. **Offline Unit/Integration Tests**: Tests in `tests/` must NOT depend on external live APIs; use fixtures in `tests/fixtures/`.
3. **No Implementation Details in GLOSSARY.md**: `GLOSSARY.md` is strictly reserved for business domain terms. Technical details belong in `docs/reference/` or `docs/adr/`.
4. **Diátaxis Discipline**: When adding docs, adhere strictly to the 4 quadrants (Tutorial, How-To, Reference, Explanation).

## Agent skills

### Issue tracker, PR base branch & PR body

GitHub issues via `gh` CLI. Feature/fix PRs use base `dev` (`gh pr create --base dev`); `main` receives only `dev` release merges. Write every PR body with the `mattpocock-skills:pr` skill. See [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md).

### Triage labels

Canonical five-role triage vocabulary. See [docs/agents/triage-labels.md](docs/agents/triage-labels.md).

### Tech debt

Tech debt lives as GitHub issues labelled `tech-debt`; code markers take the form `TODO(#123)`. See [docs/agents/tech-debt.md](docs/agents/tech-debt.md).

### Domain docs

Single-context layout (`GLOSSARY.md` + `docs/adr/`). See [docs/agents/domain.md](docs/agents/domain.md).
