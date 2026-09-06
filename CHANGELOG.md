<!-- markdownlint-disable MD024 -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- 新增台電電力供需快照擷取與 TimescaleDB 入庫，支援依觀測 slot 冪等 upsert 與手動 materialize。

### Changed

- 拆分台電快照儲存責任：將全台供需、區域供需與機組快照解耦至專屬 Repository（`TaipowerSupplyDemandRepository`、`TaipowerRegionalSupplyDemandRepository`、`TaipowerUnitGenerationRepository`），並由 `TimeSeriesRepository` 委派維持向後相容（#26）。
- 封裝 Feast 發布目標設定（`FeastPublicationTarget`）與特徵備援來源（`FallbackFeatureSources`），精簡工廠函式與特徵提取介面參數（#17）。
- 定義台電電力供需快照的資料契約、保存策略與 Dagster 擷取規則（`CONTEXT.md`、`docs/SPEC.md`）。
- 對齊套件版本字串為 `0.2.0`；前端改以 `pnpm` 與 Vite `5173` 埠啟動，避免與 Dagster `3000` 衝突。
- 統一正式 TimescaleDB DDL（`docker/init-db/01_init_hypertables.sql`）與測試 SQLite fixture 之 schema 來源，透過 DDL 方言動態轉換杜絕 schema 漂移與重複維護（#25）。

### Fixed

- 在 API 與 Dagster 映像安裝 `libgomp1`，修復 LightGBM 因缺少 OpenMP runtime 無法啟動的問題（`docker/Dockerfile.api`、`docker/Dockerfile.dagster`）。
- 修正台電即時快照在 PostgreSQL 下 raw_payload 未序列化導致寫入失敗，強化 `ParquetIOManager` 支援非 DataFrame 物件序列化，並修正 Dagster 容器工作目錄以隔絕本機 `.env` 變數污染（`src/shiro_mlops/data/repository.py`、`src/shiro_mlops/core/io_managers.py`、`docker/docker-compose.yml`）。
- 拒絕台電快照無效來源欄位：修復機組快照因缺少識別欄位產生 "None" 假識別鍵之缺陷，嚴格區分約定缺值與格式損壞，明確記錄警告並拒絕異常列，確保 TimescaleDB 不寫入假資料（#23）。

## [0.2.0] - 2026-09-04

### Added

- 新增地端 TimescaleDB 儲存層，提供 Hypertable 初始化、歷史資料 Upsert、範圍查詢，以及 Dagster 資料擷取與特徵工程整合。
- 支援 Feast 離線特徵以本機 Parquet 或 S3 發布與檢索，並提供 S3 historical feature retrieval 整合驗證。
- 新增負載、氣象資料擷取模組與 React 儀表板，支援預測、回測、漂移監控及系統診斷。
- 補充 TimescaleDB 架構決策、操作規格與 GitHub Rulesets 路線圖。

### Changed

- 將特徵計算與發布目標解耦，改由 Dagster I/O Manager 依本機或 S3 設定輸出相同 Feast 契約。
- 統一前端套件管理、系統資料契約與 GitHub Issues 追蹤流程。

### Fixed

- 修正台電與 CWA 資料轉換、台灣時區對齊、TimescaleDB 升級與特徵資料庫錯誤追蹤。
- 強化 point-in-time 正確性，隔離訓練地點與時間窗，避免跨地點或未來資料洩漏。
- 固定 Feast Parquet schema，並提升 LightGBM、MLflow 與離線整合測試的可重現性。

### Removed

- 移除已淘汰的 Streamlit 原型、舊版 npm lockfile，以及未使用的 Streamlit 與 Plotly 相依。

## [0.1.0] - 2026-08-23

### Added

- 建立 `shiro-mlops` 混合雲地架構之負載預測平台初始版本。
- 整合 Dagster SDA 排程管線（資料擷取、特徵轉換、LightGBM 模型訓練與漂移監控）。
- 整合 Feast Feature Store（Redis Online Store / Parquet Offline Store）。
- 整合 MLflow 實驗追蹤與 Model Registry。
- 實作 FastAPI 隨需推論服務（`/predict`、`/health`、`/features/latest`）。
- 建立 AWS Terraform 基礎設施配置（S3、ECR、App Runner、IAM OIDC）。

[Unreleased]: https://github.com/ShirokiXue/shiro-mlops/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/ShirokiXue/shiro-mlops/releases/tag/v0.2.0
[0.1.0]: https://github.com/ShirokiXue/shiro-mlops/releases/tag/v0.1.0
