# shiro-mlops

> - Created: 2026-08-23
> - Last Updated: 2026-11-22

Hybrid Local/AWS MLOps platform for dynamic horizon load forecasting with Feast, Dagster, MLflow, and LightGBM.

## Architecture

- **Orchestration**: Dagster (Software-Defined Assets for ingestion, feature materialization, training, evaluation, and drift detection)
- **Feature Store**: Feast (Offline Store: local Parquet under `DATA_DIR`, Online Store: Docker Redis, Registry: local)
- **Tracking & Registry**: MLflow (Self-hosted on PostgreSQL + local artifact storage)
- **Forecasting Model**: LightGBM (Recursive multi-step forecasting with dynamic exogenous weather forecasts from CWA)
- **Serving & API**: FastAPI (Dynamic horizon load predictions)
- **Monitoring**: Evidently AI (Data Drift, Target Drift, and Evaluation Metrics)
- **Infrastructure**: AWS + Terraform (S3, IAM OIDC; the cloud only serves the precomputed Forecast View, see ADR-0015)
- **Frontend**: `frontend/` pnpm workspace (React 19 + TypeScript + Vite + TanStack): the Forecast View app, the local-only Engineering Console app under `/console/`, and a shared package (ADR-0014)

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

### 5. Start the Frontend Apps

```bash
make frontend
```

Forecast View at `http://localhost:5173` and Engineering Console at `http://localhost:5174/console/` (both proxy `/api` to `http://localhost:8000`)

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
├── frontend/               # pnpm workspace: apps/forecast-view, apps/engineering-console, packages/shared
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

---

## License

The code is released under the [MIT License](LICENSE). The MIT License does not cover the source data listed below; that data stays under its own license.

## Data Sources & Attribution

The pipelines ingest the open datasets below, and `tests/fixtures/` holds trimmed samples of their payloads. Every dataset is published under the [Open Government Data License, version 1.0](https://data.gov.tw/license) (政府資料開放授權條款-第1版), which requires the attribution statement that follows the table.

| Provider | Dataset (data.gov.tw) | Endpoint |
| :--- | :--- | :--- |
| 台灣電力股份有限公司 (Taiwan Power Company) | [台灣電力公司各機組發電量即時資訊(含外購電力)](https://data.gov.tw/dataset/8931) | `d006001/001.json` |
| 台灣電力股份有限公司 (Taiwan Power Company) | [台灣電力公司今日區域別用電情況](https://data.gov.tw/dataset/162596) | `d006019/001.csv` |
| 台灣電力股份有限公司 (Taiwan Power Company) | [台灣電力公司今日系統供需狀況](https://data.gov.tw/dataset/162595) | `d006020/001.json` |
| 交通部中央氣象署 (Central Weather Administration) | [氣象觀測站-全測站逐時氣象資料](https://data.gov.tw/dataset/9176) | `O-A0001-001` |
| 交通部中央氣象署 (Central Weather Administration) | [鄉鎮天氣預報-台灣未來3天天氣預報](https://data.gov.tw/dataset/9307) | `F-D0047-089` |
| 交通部中央氣象署 (Central Weather Administration) | [鄉鎮天氣預報-台灣未來1週天氣預報](https://data.gov.tw/dataset/9308) | `F-D0047-091` |

> 台灣電力股份有限公司、交通部中央氣象署 2026 上表所列開放資料
>
> 此開放資料依政府資料開放授權條款 (Open Government Data License) 進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。
>
> 政府資料開放授權條款：<https://data.gov.tw/license>

## Contributing

Pull requests are not being accepted for now. Bug reports and questions are welcome as [GitHub issues](https://github.com/shiroki9979/shiro-mlops/issues). To report a security issue privately, use the repository's **Security → Report a vulnerability** form.
