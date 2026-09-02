<!-- markdownlint-disable MD024 -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- 實作 `engineered_features` 自 TimescaleDB 提取時序歷史視界數據並編譯產出 Feast 離線 Parquet 檔案（`taipower_features.parquet` 與 `weather_features.parquet`），驗證 Feast 離線特徵檢索與 LightGBM 訓練端到端相容（`src/shiro_mlops/pipelines/assets.py`、`src/shiro_mlops/features/definitions.py`、`tests/integration/test_feast_pipeline.py`）。
- 整合 `TimeSeriesRepository` 至 Dagster `raw_taipower_load_data` 與 `raw_weather_obs_data` 資料擷取資產，支援自動持久化寫入 TimescaleDB 與測試模式安全降級（`src/shiro_mlops/pipelines/assets.py`、`src/shiro_mlops/pipelines/definitions.py`、`tests/integration/test_pipeline_assets.py`）。

- 實作 `TimeSeriesRepository` 支援 SQLAlchemy/TimescaleDB 連線池、台電負載與氣象資料批次 Upsert（`ON CONFLICT DO UPDATE`）與時序範圍查詢（`src/shiro_mlops/data/repository.py`、`tests/unit/test_repository.py`）。


- 升級 Docker Compose 資料庫服務至 `timescale/timescaledb:latest-pg15`，並新增 `docker/init-db/01_init_hypertables.sql` 自動初始化 `raw_taipower_load` 與 `raw_cwa_weather` 7-day chunk interval Hypertables。
- 擴充 `Settings` 與 `shiro_mlops.core.database` 提供 TimescaleDB 連線參數、URI 與連線引擎輔助函式。
- 新增 `tests/unit/test_database.py` 離線單元測試，驗證 DDL 生成、檔案完整性與引擎初始化。
- 新增 ADR-0006 架構決策紀錄，確立地端 TimescaleDB 與 Parquet/S3 雙層儲存架構（`docs/adr/0006-timescaledb-local-storage-layer.md`）。
- 建立 TimescaleDB 地端時序儲存規格書（`docs/specs/timescaledb-local-storage.md`）。
- 實作 `TaipowerClient` 與 `CWAClient` 資料擷取與氣象觀測預報模組（`src/shiro_mlops/data/`）。
- 實作 React 19 SPA 儀表板，支援 1~72h 負載與氣溫雙軸走勢圖、歷史回測、資料漂移監控與系統診斷（`frontend/`）。
- 配置 Matt Pocock Agent Skills 規範文件與索引，支援 GitHub Issues 追蹤器與標準 Triage 標籤（`docs/agents/`、`AGENTS.md`）。

### Changed

- 將 Agent Skills 之 Issue Tracker 設定自 Local Markdown 遷移至 GitHub Issues，並建立 4 張 Tracer-bullet 工單（#1 ~ #4）。
- 更新系統資料契約規格書，補入 `raw_taipower_load` 與 `raw_cwa_weather` Hypertables 定義（`docs/SPEC.md`）。
- 前端套件管理切換至 pnpm，配置 `onlyBuiltDependencies` 支援 `esbuild` 與 `msw` 安裝腳本（`frontend/`）。
- 同步專案藍圖、服務端口與 Makefile，將 Milestone 1 規格更新為 React SPA 儀表板（`docs/`、`README.md`、`Makefile`）。

### Fixed

- 修復 `.gitignore` 根目錄路徑前綴，避免誤忽略 `src/shiro_mlops/data/` 與 `frontend/src/lib/`。
- 修復 `AGENTS.md` 內部文件連結之絕對路徑。

### Removed

- 移除已淘汰之 Streamlit 原型檔案 `frontend/app.py` 與舊版 `package-lock.json`。
- 移除未使用的 `streamlit` 與 `plotly` Python 依賴，精簡虛擬環境體積（`pyproject.toml`、`uv.lock`）。

## [0.1.0] - 2026-08-23

### Added

- 建立 `shiro-mlops` 混合雲地架構之負載預測平台初始版本。
- 整合 Dagster SDA 排程管線（資料擷取、特徵轉換、LightGBM 模型訓練與漂移監控）。
- 整合 Feast Feature Store（Redis Online Store / Parquet Offline Store）。
- 整合 MLflow 實驗追蹤與 Model Registry。
- 實作 FastAPI 隨需推論服務（`/predict`、`/health`、`/features/latest`）。
- 建立 AWS Terraform 基礎設施配置（S3、ECR、App Runner、IAM OIDC）。

[Unreleased]: https://github.com/ShirokiXue/shiro-mlops/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ShirokiXue/shiro-mlops/releases/tag/v0.1.0
