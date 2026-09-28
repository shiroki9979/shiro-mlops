# Feature Spec: TimescaleDB Local Time-Series Storage & Ingestion Pipeline

**Status:** superseded for CWA by ADR-0007, for Taipower load by ADR-0008, and by `docs/SPEC.md`
**Created:** 2026-08-26
**Last Updated:** 2026-09-26
**Feature Slug:** `timescaledb-local-storage`

---

> [!NOTE]
> 本文件保留 TimescaleDB 初始導入的歷史設計。CWA canonical schema、scheduled ingestion 邊界與消費契約已由 [ADR-0007](../adr/0007-isolate-cwa-access-behind-scheduled-ingestion.md) 及 [系統規格](../SPEC.md) 取代；不得將本文的 `raw_cwa_weather`、`upsert_cwa_weather` 或 `raw_weather_obs_data` 視為現行介面。台電負載來源已由 [ADR-0008](../adr/0008-derive-hourly-actual-load-from-regional-snapshots.md) 改為區域快照推算，本文的 `raw_taipower_load_data` 亦非現行介面。

---

## Problem Statement

Currently, `shiro-mlops` ingests Taipower power load and CWA weather observations directly into in-memory pandas DataFrames, converting them immediately into Parquet files. This architecture lacks an operational, relational time-series database (Bronze/Silver storage layer) on-premise, resulting in the following issues:

1. **Retroactive Data Revisions & Upserts**: Taipower occasionally revises historical load numbers or delivers delayed records. Parquet files do not support in-place updates, requiring full-file rewrites and risking data inconsistency.
2. **Ad-hoc Time-Series Querying & Visualization**: Operators and engineers cannot query raw time-series records using standard SQL, time-bucketing (`time_bucket`), or connect visualization tools (e.g. Grafana, DBeaver) directly to live operational data.
3. **Pipeline Replayability**: Without raw data persistence in a structured operational store, re-running feature engineering with modified lag/rolling parameters requires re-downloading data from external APIs.

---

## Solution

Upgrade the local Docker container environment from vanilla PostgreSQL to TimescaleDB, create structured Hypertables for raw Taipower load and CWA weather observations, and update Dagster ingestion assets to persist incoming API payloads with deduplication (`ON CONFLICT DO UPDATE`).

Establish a clean export seam from TimescaleDB into Parquet (`data/taipower_features.parquet`) for Feast Feature Store and downstream LightGBM model training, strictly preserving zero-idle-cost cloud compatibility as defined in [ADR-0001](../adr/0001-hybrid-topology-boundary.md), [ADR-0002](../adr/0002-feast-storage-layer-strategy.md), and [ADR-0006](../adr/0006-timescaledb-local-storage-layer.md).

---

## User Stories

1. As a Data Engineer, I want the local Docker Compose stack to provision a TimescaleDB instance automatically, so that I have an operational time-series database running with zero manual setup.
2. As a Data Engineer, I want dedicated Hypertables for `raw_taipower_load` and `raw_cwa_weather` partitioned by timestamp, so that high-volume time-series data is indexed and chunked efficiently.
3. As an MLOps Engineer, I want Taipower ingestion assets to execute idempotent upserts (`ON CONFLICT DO UPDATE`) on `(time, location)` primary keys, so that duplicate or retroactively corrected load data does not create duplicate rows.
4. As an MLOps Engineer, I want CWA weather observation ingestion assets to upsert hourly temperature and relative humidity readings into TimescaleDB, so that historical weather observations are persistently archived locally.
5. As a Data Scientist, I want to query historical electricity load and weather observations using standard SQL and `time_bucket` aggregations, so that I can analyze power consumption patterns and perform data sanity checks easily.
6. As a Data Scientist, I want Dagster feature assets to extract verified time-series slices from TimescaleDB and compile them into Parquet artifacts, so that Feast Feature Store and LightGBM model training receive consistent, time-aligned datasets.
7. As a Cloud DevOps Engineer, I want Feast Offline Store to continue consuming Parquet files from S3 / Local filesystem, so that cloud training and serverless API inference require no permanent cloud database instances.
8. As a Maintainer, I want unit and integration tests to verify database migrations, upsert operations, and Parquet export formatting using mocked database connections or test fixtures, so that CI remains completely offline and deterministic.

---

## Implementation Decisions

### 1. Storage & Container Infrastructure

- Upgrade local Docker Compose database service from `postgres:15-alpine` to `timescale/timescaledb:latest-pg15`.
- Maintain unified service credentials and persistence volume (`postgres_data`) to support both MLflow backend metadata and TimescaleDB time-series tables.
- Add configuration parameters (`TIMESCALE_HOST`, `TIMESCALE_PORT`, `TIMESCALE_DB`, `TIMESCALE_USER`, `TIMESCALE_PASSWORD`) in application settings with sensible local defaults.

### 2. Database Schema & Hypertables

- Define DDL migrations/scripts creating two primary Hypertables:
  - `raw_taipower_load`: `(time TIMESTAMPTZ NOT NULL, location VARCHAR(64) NOT NULL, load_mw DOUBLE PRECISION NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW(), PRIMARY KEY (time, location))`
  - `raw_cwa_weather`: `(time TIMESTAMPTZ NOT NULL, location VARCHAR(64) NOT NULL, temperature DOUBLE PRECISION, relative_humidity DOUBLE PRECISION, created_at TIMESTAMPTZ DEFAULT NOW(), PRIMARY KEY (time, location))`
- Configure TimescaleDB 7-day chunk intervals for efficient indexing and time-window queries.

### 3. Repository Layer & Ingestion Pipeline

- Implement a dedicated database repository (`TimeSeriesRepository`) providing:
  - `upsert_taipower_load(df: pd.DataFrame) -> int`
  - `upsert_cwa_weather(df: pd.DataFrame) -> int`
  - `fetch_load_range(start_time: datetime, end_time: datetime, location: str) -> pd.DataFrame`
  - `fetch_weather_range(start_time: datetime, end_time: datetime, location: str) -> pd.DataFrame`
- Refactor Dagster assets:
  - `raw_taipower_load_data`: Fetch from API client -> Upsert into TimescaleDB -> Return DataFrame.
  - `raw_weather_obs_data`: Fetch from API client -> Upsert into TimescaleDB -> Return DataFrame.
  - `engineered_feature_set` (multi-asset): Pull clean time-series from TimescaleDB (or upstream assets) -> Compute lag/rolling transforms -> Emit `engineered_features` / `taipower_features` / `weather_features`（後兩者由 `feast_io_manager` 發布至本機或 S3 Parquet）。

### 4. Feast Feature Store Seam

- Feast `FileSource` in feature definitions continues to point to `data/taipower_features.parquet` and `data/weather_features.parquet`.
- Feast remains completely decoupled from TimescaleDB connection details, preserving zero-cloud-cost portability.

---

## Testing Decisions

### Seams & Boundaries

1. **Database Client & Upsert Seam (`TimeSeriesRepository`)**:
   - Verify SQL DDL generation, connection pooling, and `ON CONFLICT DO UPDATE` batch execution.
   - Tested with SQLite / PostgreSQL / SQLAlchemy test engine mocks.
2. **Dagster Asset Integration Seam**:
   - Verify asset materialization sequence: API fetch -> DB upsert -> Parquet generation -> Model training.
   - Tested using Dagster's in-process test execution (`materialize`) with fixture data.
3. **Data Parity & Feast Contract Seam**:
   - Verify that Parquet output generated from TimescaleDB records matches expected Feast schema (Float32, Int64 types, timestamp columns).

---

## Out of Scope

- Setting up AWS RDS TimescaleDB (cloud database is explicitly out of scope per ADR-0001 / ADR-0002).
- Continuous real-time streaming ingestion via Kafka / Flink (batch hourly ingestion via Dagster is sufficient).
- Setting up Grafana dashboards (reserved for future monitoring tickets).

---

## Further Notes

- References:
  - [ADR-0001: Hybrid Topology Boundary](../adr/0001-hybrid-topology-boundary.md)
  - [ADR-0002: Feast Storage Layer Strategy](../adr/0002-feast-storage-layer-strategy.md)
  - [ADR-0006: Local TimescaleDB Storage Layer](../adr/0006-timescaledb-local-storage-layer.md)
  - [SPEC.md: Data Contracts](../SPEC.md)
