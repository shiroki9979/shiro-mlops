<!-- markdownlint-disable MD024 -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- 新增可選 TimescaleDB 整合測試，驗證台灣時間與 UTC 輸入的儲存瞬間、Upsert 冪等性、範圍查詢與特徵合併對齊（`tests/integration/test_timescaledb_repository.py`，#13）。
- 支援 Feast 離線特徵發布至 S3 或本機檔案系統，實作 `publish_parquet_feature` 儲存發布模組（`src/shiro_mlops/features/storage.py`，#12）。
- 於 `Settings` 增加 `FEAST_OFFLINE_STORE_TYPE`、`FEAST_S3_PREFIX` 與動態 Parquet URI 屬性，並更新 `definitions.py` 動態支援 S3 與本機 FileSource 檢索（`src/shiro_mlops/core/config.py`、`src/shiro_mlops/features/definitions.py`，#12）。
- 於 Dagster `engineered_features` 資產中整合 S3 特徵檔發布，維持雲端無常駐資料庫之混合拓撲架構（`src/shiro_mlops/pipelines/assets.py`，#12）。
- 新增本機與 S3 特徵發布、資料契約一致性與 Feast 來源動態切換之整合測試（`tests/integration/test_feast_pipeline.py`，#12）。
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

- 修正特徵資料庫讀取失敗時的靜默降級：僅處理可預期的 SQLAlchemy 錯誤、記錄診斷脈絡並保留 ingestion 回退資料；同時統整 Feast 匯出預設值與欄位正規化（`src/shiro_mlops/pipelines/feature_pipeline.py`、`tests/unit/test_feature_pipeline.py`，#13、#14）。
- 統一台電用電負載與氣象觀測之時區語意為台灣本地時間（`Asia/Taipei`），實作 `standardize_taiwan_datetime` 函式處理無時區、含時區偏移（`+08:00`）與 UTC（`Z`）時間戳記（`src/shiro_mlops/core/datetime_utils.py`、`src/shiro_mlops/data/taipower_client.py`、`src/shiro_mlops/data/cwa_client.py`，#11）。
- 於 `TimeSeriesRepository` 與特徵工程（`transformers.py`）讀寫與合併前強制進行台灣本地時區對齊，確保多資料源在完全相同之時間基準上合併與計算時序特徵，徹底杜絕 8 小時偏移問題（`src/shiro_mlops/data/repository.py`、`src/shiro_mlops/features/transformers.py`，#11）。
- 新增時區對齊之單元與整合測試，涵蓋無時區、`+08:00` 與 UTC 混合來源（`tests/unit/test_transformers.py`、`tests/integration/test_data_clients.py`，#11）。
- 實作地端資料庫自動檢查與遷移機制 `ensure_timescale_hypertables`，於 `TimeSeriesRepository` 與 API 服務啟動時自動建立或升級 Hypertable（`src/shiro_mlops/core/database.py`、`src/shiro_mlops/data/repository.py`、`src/shiro_mlops/service/api.py`，#10）。

- 在 TimescaleDB 初始化 DDL 加入 `migrate_data => TRUE`，確保既有已含觀測資料之資料卷無痛升級為 Hypertable 且零資料遺失（`docker/init-db/01_init_hypertables.sql`，#10）。
- 新增既有資料卷升級、重複啟動冪等性與保留資料之離線測試（`tests/unit/test_database.py`，#10）。
- 隔離 LightGBM 與 MLflow 離線測試環境，在測試模式下自動注入輕量或 mock forecaster，並將 MLflow tracking 後端切換為本機隔離 SQLite / Mock，大幅提升端到端測試穩定度與執行速度（`src/shiro_mlops/pipelines/assets.py`、`tests/conftest.py`、`tests/integration/test_feast_pipeline.py`，#9）。

- 將重複之 SQLite schema、Engine、Repository 與 DagsterInstance fixtures 統整至 `tests/conftest.py`，徹底消除測試資料庫定義漂移與資源競爭問題（`tests/conftest.py`、`tests/integration/test_pipeline_assets.py`、`tests/unit/test_repository.py`、`tests/unit/test_database.py`，#9）。
- 統一 TimescaleDB 資料庫名稱契約為 `shiro_timeseries`，同步更新 `src/shiro_mlops/core/config.py`、`docker/docker-compose.yml`、`.env.example` 與單元測試（#8）。
- 實作 Feast Parquet Schema 固定合約防護，確保即使為不足長度之短資料視界，亦包含 `load_mw_lag_24`、`load_mw_rolling_mean_24` 等所有必填特徵欄位與相容型別（`float32` / `int64`）（`src/shiro_mlops/features/transformers.py`、`src/shiro_mlops/pipelines/assets.py`，#8）。
- 定義明確的短期視界缺失值後向填補（`bfill`）與平均值常模補值策略，並加入短資料集與設定一致性離線測試（`tests/integration/test_feast_pipeline.py`、`tests/unit/test_database.py`，#8）。
- 修正 `transformers.py` 特徵工程依 `location` 隔離計算 lag 與 rolling 時序特徵，並改以 `(datetime, location)` 對齊氣象特徵與分組填值，徹底消除多測站笛卡兒積與特徵污染（`src/shiro_mlops/features/transformers.py`，#7）。
- 修正 `engineered_features` 資產確保產出之 Feast Parquet 包含唯一 `(datetime, location)` 實體鍵與時間對齊（`src/shiro_mlops/pipelines/assets.py`，#7）。
- 新增多地點離線防回歸測試，驗證跨測站時序特徵無相互污染（`tests/unit/test_transformers.py`、`tests/integration/test_feast_pipeline.py`，#7）。
- 修正 `TaipowerClient` 支援解析真實 CSV 與 JSON 資料源，並將萬瓩單位與中文欄位標準化為 `datetime` 與 `load_mw`（`src/shiro_mlops/data/taipower_client.py`，#6）。
- 修正 `CWAClient` 支援解析真實巢狀 `O-A0001-001` 觀測 payload，萃取 `location`、`time`、`temperature` 與 `relative_humidity`（`src/shiro_mlops/data/cwa_client.py`，#6）。
- 新增真實 API 離線測試 fixtures（`taipower_sample.csv`、`cwa_obs_nested_sample.json`）並整合 Dagster Ingestion 至 TimescaleDB Upsert 端到端驗證（`tests/fixtures/`、`tests/integration/test_data_clients.py`、`tests/integration/test_pipeline_assets.py`，#6）。
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
