<!-- markdownlint-disable MD024 -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- 新增可追溯的 CWA 觀測與預報版本本機資料服務，供訓練與推論讀取 canonical TimescaleDB 資料（#30）。
- 新增唯讀營運資料檢視器（Data Explorer）：六個 typed datasets、CWA ingestion audits、共用狀態契約與 cursor 分頁，並在 Monitoring 顯示 Data Source Status（#40–#49）。
- 側邊欄在 Data Explorer 啟用時列出六個 typed datasets 與 CWA audits nested routes。
- 新增由台電區域供需快照推算的全台逐時實際負載與每小時 `hourly_actual_load_job`，取代已失效的 d015046 歷史來源；只往前累積、不回補歷史（#59，ADR-0008）。
- 新增負載起點過舊防護：最新推算負載落後請求時間超過任務設定 `stale_anchor_max_lag_hours`（預設 3 小時）時，`/ready` 與 `/predict` 回傳 HTTP 503；氣象過期時依來源標示降級（#62）。
- 新增 `make smoke-check` 排程與下游就緒檢查，以及 d015046 舊列清除與冷啟動恢復操作指南（#59、#60）。
- 新增通用任務端點 `POST /tasks/{task_id}/predict` 與 `GET /tasks/{task_id}/ready`，逐任務載入模型；`/predict`、`/ready` 保留為動態視界預報任務的別名（#68）。
- 新增高負載預警任務 `high_load_alert`（`direct_classification` 任務類型，`LGBMClassifier`），以錨點前 28 日逐時負載的 P90 為門檻；門檻窗負載不完整時拒絕訓練，預測回傳 HTTP 503（#69）。
- 新增用電型態異常偵測任務 `load_pattern_anomaly`（`unsupervised_reconstruction` 任務類型，MLP AutoEncoder 以 `.npz` 保存並以 numpy 前向計算），推論改用觀測天氣，誤報率以交錯日期的保留窗評估；缺少完整評分窗時 `/ready` 不回報就緒（#70）。
- Data Explorer 在翻頁 cursor 失效（HTTP 400）時提供「Back to first page」操作，保留目前的時間窗口與篩選；明確指定的預報版本亦保留（#73、#77）。

### Changed

- 引入 ML 任務抽象（ADR-0009）：動態視界預報改由 `src/shiro_mlops/tasks/dynamic_horizon_forecast.toml` 任務設定與 `recursive_regression` 任務類型描述，Dagster 與 API 只經 task runner 訓練與預測；lag／rolling 配方以任務設定為唯一來源，serving 依 `lookback_hours` 有界讀取負載歷史（#66）。
- 每日訓練與每小時 drift 改依有效逐時負載累積量啟用：少於任務設定 `min_training_hours`（預設 672 小時）時拒絕訓練，drift 以有界查詢讀取最新實際負載（#60）。
- 模型改以原生非執行格式加 JSON metadata 保存於 `DATA_DIR/models/<task_id>/`（LightGBM 文字格式、AutoEncoder `.npz`，ADR-0010），並以原子目錄交換替換，替換中斷或讀取期間皆保有完整模型；既有 `DATA_DIR/model.joblib` 不再載入，首次重新訓練前 `/ready` 維持 not_ready（#66）。
- Dagster 改以資產工廠依任務設定產生每個任務的 `{task_id}__features`／`__model`／`__monitoring` 資產、訓練與監控 job 及 Asia/Taipei 排程（cron 來自任務設定 `[schedule]`）；`daily_training_job`／`hourly_drift_job` 與其排程、`trained_forecaster_model` 等資產鍵由 `dynamic_horizon_forecast__*` 取代，舊鍵 materialization 歷史不轉移，新排程需重新開啟並先完成一次訓練。每個任務以 `task_id` 命名獨立的 MLflow experiment 與 registered model；監控健康判定改由任務類型依任務設定 `[health]` 門檻決定，取代寫死的 `mape < 10.0`，驗證期為空時回報 WARNING；Feast 匯出只掛在動態視界預報任務（#67）。
- 預測 item 的天氣欄位改依任務設定 `weather.fields` 產生，不再由任務類型寫死氣溫與濕度；通用端點 OpenAPI 以每個任務的 `<TaskId>TaskPredictionResponse`（以 `task_id` 常數區分）描述回應，`/predict` 的 `PredictionItem` 契約不變（#69）。
- 拆分預測對象與氣象代表點（ADR-0009）：`raw_taipower_load.location` 改名為 `subject`，全台負載由 `Taipei` 遷移為 `nationwide`（服務啟動時自動且可重複遷移，操作順序見 `docs/how-to/migrate-load-subject-to-nationwide.md`）；天氣解析與訓練天氣改以 CWA 擷取目錄的氣象代表點 alias 取值；`/predict` 回應以 `subject` 取代 `location`；Data Explorer 逐時負載改以 `subject` 顯示與篩選，儀表板移除地點選單（#65）。
- CWA 觀測與預報擷取、台電區域快照改為有限次數的指數退避重試（#59、#62）。
- 天氣預報 staleness 判定改以請求時間為 `as_of`，serving 只使用推算口徑的逐時負載（#62）。
- Data Explorer 八個資料集統一分頁規則：依每個資料集宣告的完整複合排序鍵（最新優先）翻頁，cursor 升為 v2 並保留資料庫原始微秒精度，時間窗口嚴格採用閉區間 `[start, end]`，預報最新版本於第一頁解析後跨頁固定；缺口計算的預期 slot 自窗口內第一個整點／十分鐘 slot 起算，窗口起點前的 slot 不再列入 `missing_slots`（#72–#77）。
- 將 Data Explorer 列表查詢抽出為 typed `ExplorerQuery`，並讓逐時負載改走共用 cursor／keyset 分頁 seam（#52）。
- 將 CWA 觀測、鄉鎮預報與 audit 列表遷移至 typed query 上的 focused readers，保留 vintage 與 missing-identifier 契約（#53）。
- 將全台／區域供需與機組發電列表遷移至 typed query readers，保留 MW 轉換、完整度與 nullable 欄位契約（#54）。
- 將 Data Explorer 狀態彙總抽成 focused collaborators，並移除單體 `DataExplorerStore`（#55）。
- 簡化 Data Explorer 電力與預報 reader 的查詢、映射與測試資料 seam，讓列表契約可獨立維護與驗證。

### Deprecated

- `/predict` 的 `location` 請求欄位改為選填並於 OpenAPI 標示 deprecated；任何值皆被忽略，不再回傳 HTTP 400（#65）。

### Removed

- 移除 d015046 擷取路徑：`raw_taipower_load_data` 資產、`TaipowerClient` 與 `TAIPOWER_API_URL` 設定（#59）。
- 移除 `MLFLOW_EXPERIMENT_NAME`、`TRAINING_MIN_LOAD_HOURS` 與 `LOAD_ANCHOR_MAX_LAG_HOURS` 設定：MLflow experiment 名稱改由任務 id 推導，訓練門檻與負載起點落後上限改由任務設定 `[policies]` 管理（#66、#67）。
- 移除 `FallbackFeatureSources` 與特徵查詢窗等訓練備援路徑，以及 `predict_recursive` 的固定氣象預設值（#66）。
- 移除 `merge_weather_features` 與 `build_feature_pipeline` 的 `strict_weather` 參數與非 strict 分支：天氣一律只取兩小時內的過去觀測，缺值保留而不再以 25.0／70.0 常數或未來觀測補值（#66）。
- 移除誤標為 Feast 的 Monitoring Feature Store Snapshot 與 `GET /features/latest` 過渡端點（#50）。
- Data Explorer 不再接受 v1 cursor，並移除時間窗口起訖各放寬一秒的查詢補償（#77）。

### Fixed

- 修正推算負載缺漏小時造成遞迴預報與 Feast 匯出 lag／rolling 特徵時距錯位，改依實際小時時間戳計算；僅起始 warm-up 缺值補零，避免中段缺漏被相鄰負載冒充（#59、#66）。
- 修正 Data Explorer 翻頁以整秒顯示時間重建 cursor，導致同秒不同微秒的觀測批次、預報版本跨頁遺漏；並修正窗口放寬一秒時列表與完整度混入窗外資料（#73–#77）。
- 確保 CWA 兩種預報產品先完成擷取再於單一交易入庫，避免第二種產品失敗後留下不完整的新版本（#62）。
- 訓練、特徵擷取與 Data Explorer 逐時負載列表、缺口及狀態僅讀取推算口徑的逐時負載，忽略尚未清除的 d015046 舊列；資料庫升級無法檢查 schema 時明確回報失敗（#59、#60）。
- 就緒檢查與預測遇到非預期錯誤時記錄完整堆疊，不再只把錯誤訊息轉成 not_ready 或 HTTP 500 而遺失真因。
- 資料庫中斷時觀測天氣推論回傳 HTTP 503（Persistence unavailable），不再吞下錯誤而誤報為缺少觀測天氣（#70）。
- 改由 CWA 原始 XML 預報檔取得 `IssueTime`／`Update`，並限制無憑證下載 redirect 的 HTTPS 儲存目標，避免 flattened REST 回應缺少版本時間而使 forecast ingestion 永久重試。
- 讓 `make compose-up` 以根目錄 `.env` 做 Compose 插值，把 `CWA_API_KEY` 注入 Dagster／API 容器，避免空授權碼導致 CWA 入庫 401。
- 拒絕缺少或無法解析 `IssueTime`／`Update` 的 CWA 預報回應，避免以擷取時間偽造版本而破壞冪等與 stale 判定。
- 修正 Timescale schema 初始化把 SQL 註解裡的分號當成語句分隔，導致既有 volume 建不出 `raw_cwa_forecast_release`。
- 讓 Dagster `ParquetIOManager` 能把 CWA 預報 dataclass 序列化成 JSON artifact，避免入庫成功後仍因無法寫出資產而失敗。
- 拒絕 Data Explorer audit 非陣列 missing-identifier payload；keyset cursor 改以 naive UTC 比對，避免 SQLite 重複回傳當前列；並補齊電力列表空結果／非法查詢／分頁與預報 `issued_at` 契約測試。
- 修正區域完整度在分頁截斷後才篩選、預報最新版本跨頁漂移與遺漏 `valid_to` cursor key 的問題；incomplete audit 即使未列出缺失識別碼也能正確呈現狀態。
- 隔離缺乏可信 StationId provenance 的舊版 CWA 氣象資料，並禁止 legacy 寫入混入 canonical 觀測資料。
- 修正 point-in-time 預報版本選取、風向插值與訓練氣象缺口處理，避免未來資料洩漏及固定值回填。

## [0.3.0] - 2026-09-06

### Added

- 新增台電電力供需快照擷取與 TimescaleDB 入庫，支援依觀測 slot 冪等 upsert 與手動 materialize。

### Changed

- 拆分台電快照儲存責任：將全台供需、區域供需與機組快照解耦至專屬 Repository（`TaipowerSupplyDemandRepository`、`TaipowerRegionalSupplyDemandRepository`、`TaipowerUnitGenerationRepository`），並由 `TimeSeriesRepository` 委派維持向後相容（#26）。
- 封裝 Feast 發布目標設定（`FeastPublicationTarget`）與特徵備援來源（`FallbackFeatureSources`），精簡工廠函式與特徵提取介面參數（#17）。
- 定義台電電力供需快照的資料契約、保存策略與 Dagster 擷取規則（`CONTEXT.md`、`docs/SPEC.md`）。
- 對齊套件版本字串為 `0.2.0`；前端改以 `pnpm` 與 Vite `5173` 埠啟動，避免與 Dagster `3000` 衝突。
- 統一正式 TimescaleDB DDL（`docker/init-db/01_init_hypertables.sql`）與測試 SQLite fixture 之 schema 來源，透過 DDL 方言動態轉換杜絕 schema 漂移與重複維護（#25）。

### Fixed

- 修正機組容量比格式與備註缺值處理，拒絕重複百分比符號並保留非空來源備註（#23）。
- 修正 `TimeSeriesRepository` 在 `auto_init=False` 時仍建立快照資料表的副作用，改由 aggregate repository 統一初始化 schema（#26）。
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

[Unreleased]: https://github.com/shiroki9979/shiro-mlops/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/shiroki9979/shiro-mlops/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/shiroki9979/shiro-mlops/releases/tag/v0.2.0
[0.1.0]: https://github.com/shiroki9979/shiro-mlops/releases/tag/v0.1.0
