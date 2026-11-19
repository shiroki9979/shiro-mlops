# shiro-mlops

- Created: 2026-08-23
- Last updated: 2026-11-19

Hybrid Local/AWS MLOps platform for dynamic horizon load forecasting with Feast, Dagster, MLflow, and LightGBM.

## Architecture

- **Orchestration**: Dagster (Software-Defined Assets for ingestion, feature materialization, training, evaluation, and drift detection)
- **Feature Store**: Feast (Offline Store: Parquet on S3/Local, Online Store: Docker Redis, Registry: S3/Local)
- **Tracking & Registry**: MLflow (Self-hosted on PostgreSQL + S3/Local artifact storage)
- **Forecasting Model**: LightGBM (Recursive multi-step forecasting with dynamic exogenous weather forecasts from CWA)
- **Serving & API**: FastAPI (Dynamic horizon load predictions)
- **Monitoring**: Evidently AI (Data Drift, Target Drift, and Evaluation Metrics)
- **Infrastructure**: AWS + Terraform (S3, IAM OIDC; the cloud only serves the precomputed Forecast View, see ADR-0015)
- **Frontend Dashboard**: `frontend/` (React 19 + TypeScript + Vite + TanStack SPA)

---

## Quickstart (Local Development)

### 1. Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- Node.js 20+ and [pnpm](https://pnpm.io/) (for frontend dashboard)
- Docker & Docker Compose (optional for full container mode)

### 2. Installation

```bash
make install
```

### 3. Run Tests

```bash
make test
```

### 4. Start Local Development API

```bash
make dev
```

API docs available at: `http://localhost:8000/docs`

### 5. Start Frontend Dashboard

```bash
make frontend
```

Dashboard available at: `http://localhost:5173` (proxies `/api` to `http://localhost:8000`)

### 6. Start Dagster Pipeline Webserver

```bash
make dagster
```

Dagster UI available at: `http://localhost:3000`

---

## Directory Structure

```text
shiro-mlops/
├── .github/workflows/      # CI/CD pipelines
├── docker/                 # Docker Compose, Dockerfiles, TimescaleDB init SQL
├── frontend/               # React 19 + Vite Dashboard SPA
├── infra/terraform/        # AWS Infrastructure as Code
├── src/shiro_mlops/
│   ├── core/               # Config, DB, IO managers, datetime helpers
│   ├── data/               # Taipower/CWA clients, TimescaleDB repository
│   ├── features/           # Feast definitions and frozen export, storage, transformers
│   ├── models/             # Forecast evaluation metrics shared by task types
│   ├── pipelines/          # Dagster assets, schedules, smoke check
│   ├── service/            # FastAPI application
│   └── tasks/              # ML task definitions (*.toml), task types, runner, model store
├── tests/
│   ├── fixtures/           # Mock data fixtures
│   ├── unit/               # Unit tests
│   └── integration/        # Integration tests
├── Makefile
└── pyproject.toml
```
