# shiro-mlops

Hybrid Local/AWS MLOps platform for dynamic horizon load forecasting with Feast, Dagster, MLflow, and LightGBM.

## Architecture

- **Orchestration**: Dagster (Software-Defined Assets for ingestion, feature materialization, training, evaluation, and drift detection)
- **Feature Store**: Feast (Offline Store: Parquet on S3/Local, Online Store: Docker Redis, Registry: S3/Local)
- **Tracking & Registry**: MLflow (Self-hosted on PostgreSQL + S3/Local artifact storage)
- **Forecasting Model**: LightGBM (Recursive multi-step forecasting with dynamic exogenous weather forecasts from CWA)
- **Serving & API**: FastAPI (Dynamic horizon load predictions)
- **Monitoring**: Evidently AI (Data Drift, Target Drift, and Evaluation Metrics)
- **Infrastructure**: AWS + Terraform (S3, ECR, App Runner, IAM OIDC)
- **Frontend Stub**: `frontend/` (Independent stub directory for future UI integration)

---

## Quickstart (Local Development)

### 1. Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
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

### 5. Start Dagster Pipeline Webserver

```bash
make dagster
```

Dagster UI available at: `http://localhost:3000`

---

## Directory Structure

```text
shiro-mlops/
├── .github/workflows/      # CI/CD pipelines
├── docker/                 # Docker Compose & Dockerfiles
├── frontend/               # Frontend UI stub
├── infra/terraform/        # AWS Infrastructure as Code
├── src/shiro_mlops/
│   ├── core/               # Configuration, IO managers, constants
│   ├── data/               # Taipower and CWA API clients
│   ├── features/           # Feast definitions and transformers
│   ├── models/             # LightGBM recursive forecaster and evaluator
│   ├── pipelines/          # Dagster assets and schedules
│   └── service/            # FastAPI application
├── tests/
│   ├── fixtures/           # Mock data fixtures
│   ├── unit/               # Unit tests
│   └── integration/        # Integration tests
├── Makefile
└── pyproject.toml
```
