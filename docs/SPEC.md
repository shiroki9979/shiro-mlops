# 系統規格與資料契約規格書 (SPEC.md)

- 建立日期：2026-08-23
- 最後更新：2026-09-06
- 專案版本：`0.3.0`

---

## 1. 資料模型與契約 (Data Contracts)

### 1.1 台電用電負載實體 (Taipower Load Schema)

- **資料來源**：台電開放資料（CSV/API）
- **欄位契約**：

| 欄位名稱 | 型態 | 單位/範例 | 說明 |
| :--- | :--- | :--- | :--- |
| `datetime` | `datetime64[ns]` | `2026-08-20 14:00:00` | 時間戳記（逐時） |
| `load_mw` | `float64` | `39800.0` | 當前系統總用電負載（百萬瓦） |

### 1.2 中央氣象署觀測與預報實體 (CWA Weather Schema)

- **資料來源**：中央氣象署 OpenData API
- **欄位契約**：

| 欄位名稱 | 型態 | 單位/範例 | 說明 |
| :--- | :--- | :--- | :--- |
| `datetime` | `datetime64[ns]` | `2026-08-20 14:00:00` | 時間戳記（逐時） |
| `temperature` | `float64` | `35.5` | 觀測/預報氣溫（攝氏度） |
| `relative_humidity` | `float64` | `65.0` | 相對濕度（百分比） |
| `location` | `string` | `Taipei` | 觀測站/預報區域 |

### 1.3 地端時序資料庫模型 (TimescaleDB Hypertables)

- **資料庫**：`shiro_timeseries` (TimescaleDB / PostgreSQL 15+)
- **時間契約**：擷取與特徵工程邊界的無時區時間均表示台灣本地時間（`Asia/Taipei`）；帶時區的來源時間保留其原始瞬間。寫入 `TIMESTAMPTZ` 前，repository 一律轉為 UTC；範圍查詢條件同樣轉為 UTC。讀回資料在交給特徵工程前轉回無時區的台灣本地時間。
- **主表結構**：
  1. `raw_taipower_load`:
     - `time` (TIMESTAMPTZ, NOT NULL)
     - `location` (VARCHAR(64), NOT NULL)
     - `load_mw` (DOUBLE PRECISION, NOT NULL)
     - `created_at` (TIMESTAMPTZ DEFAULT NOW())
     - **Constraint**: `PRIMARY KEY (time, location)`
     - **Hypertable**: `create_hypertable('raw_taipower_load', 'time')`
  2. `raw_cwa_weather`:
     - `time` (TIMESTAMPTZ, NOT NULL)
     - `location` (VARCHAR(64), NOT NULL)
     - `temperature` (DOUBLE PRECISION)
     - `relative_humidity` (DOUBLE PRECISION)
     - `created_at` (TIMESTAMPTZ DEFAULT NOW())
     - **Constraint**: `PRIMARY KEY (time, location)`
     - **Hypertable**: `create_hypertable('raw_cwa_weather', 'time')`
  3. `raw_taipower_supply_demand_snapshot`:
     - **資料來源**：台電官方開放資料端點 `https://service.taipower.com.tw/data/opendata/apply/file/d006020/001.json`。
     - 保存台電電力供需快照，與 `raw_taipower_load` 的逐時實際負載資料分離，且不得成為既有訓練特徵的輸入。
     - `observed_at` (TIMESTAMPTZ, NOT NULL)：Dagster 排程觸發的快照觀測時間，為唯一鍵；同一排程 tick 重跑時更新同一筆快照。
     - `source_publish_time` (TIMESTAMPTZ, NULL)：來源 payload 的預估尖峰發布時間，僅作資料欄位，不參與唯一鍵。
     - 功率欄位以來源單位 `萬瓩` 保存，欄位名使用 `*_wan_kw`；使用率與備轉率使用 `*_pct`。typed 欄位包括目前用電／使用率、預估最大供電能力／尖峰用電／備轉容量／備轉率／指標／尖峰時段、昨日日期與對應尖峰供需資訊，以及實際最高供電能力與尖峰時間。
     - `raw_payload` (JSONB, NOT NULL) 保存完整成功回應；原始字串中的民國曆發布時間同時解析至 `source_publish_time`，並以 `Asia/Taipei` 解讀後寫入 UTC。
     - 永久保留歷史快照，不設定資料保留政策。
  4. `raw_taipower_regional_supply_demand_snapshot`:
     - **資料來源**：台電官方開放資料端點 `https://service.taipower.com.tw/data/opendata/apply/file/d006019/001.csv`（政府資料開放平臺資料集「今日區域別用電情況」）。
     - 保存北、中、南、東四區的區域發電量與區域用電負載成對快照，與全台 `raw_taipower_supply_demand_snapshot` 及 `raw_taipower_load` 分離，且不得成為既有訓練特徵的輸入。
     - `observed_at` (TIMESTAMPTZ, NOT NULL)：Dagster 排程觸發的快照觀測時間。
     - `region` (VARCHAR(16), NOT NULL)：來源區域名稱，正規化後為 `北部`／`中部`／`南部`／`東部`。
     - **Constraint**: `PRIMARY KEY (observed_at, region)`；同一排程 tick 重跑時更新同一區域快照。
     - `source_time` (TIMESTAMPTZ, NOT NULL)：來源 CSV `時間` 欄位（`YYYYMMDDTHHMMSS`，以 `Asia/Taipei` 解讀後寫入 UTC）。
     - 功率欄位以來源單位 `萬瓩` 保存：`generation_wan_kw`（可為 NULL）、`load_wan_kw`（必填）。
     - `raw_payload` (JSONB, NOT NULL) 保存該列來源欄位物件。
     - 永久保留歷史快照，不設定資料保留政策。
  5. `raw_taipower_unit_generation_snapshot`:
     - **資料來源**：台電官方開放資料端點 `https://service.taipower.com.tw/data/opendata/apply/file/d006001/001.json`（政府資料開放平臺資料集「各機組發電量即時資訊(含外購電力)」）。
     - 保存台電自有及外購電力各機組即時淨發電量快照，與全台／區域供需快照及 `raw_taipower_load` 分離，且不得成為既有訓練特徵的輸入。
     - `observed_at` (TIMESTAMPTZ, NOT NULL)：Dagster 排程觸發的快照觀測時間。
     - `unit_type` (VARCHAR(128), NOT NULL)：來源 `機組類型`（去除明顯 HTML 標記後保存）。
     - `unit_name` (VARCHAR(128), NOT NULL)：來源 `機組名稱`，為機組識別之一部分。
     - **Constraint**: `PRIMARY KEY (observed_at, unit_type, unit_name)`；同一排程 tick 重跑時更新同一機組快照。
     - `source_time` (TIMESTAMPTZ, NOT NULL)：來源 payload 的 `DateTime`（以 `Asia/Taipei` 解讀後寫入 UTC）。
     - 功率與比率以來源單位保存：`capacity_mw`、`net_generation_mw`（可為 NULL，含 `N/A` 或 `-`）、`capacity_ratio_pct`（可為 NULL；來源百分比字串去除 `%` 後保存）、`remark`（可為 NULL；空白備註視為空值）。零發電（`0.0`）為合法數值並保留停機／歲修等備註。
     - `raw_payload` (JSONB, NOT NULL) 保存該次成功回應的完整 JSON，包含頂層 `DateTime` 與全部 `aaData` 機組列。
     - 永久保留歷史快照，不設定資料保留政策。

### 1.4 Feast 特徵庫視圖 (Feature View Schema)

- **Entity**: `location` (Join Key: `location`)
- **Features (`taipower_load_features`)**:
  - `load_mw`: float32
  - `load_mw_lag_1`, `load_mw_lag_2`, `load_mw_lag_24`: float32
  - `load_mw_rolling_mean_6`, `load_mw_rolling_mean_24`: float32
  - `hour`, `dayofweek`, `is_weekend`: int64
  - `hour_sin`, `hour_cos`: float32
- **Features (`cwa_weather_features`)**:
  - `temperature`: float32
  - `relative_humidity`: float32
- **時間正確性**：特徵擷取必須提供明確的 `FeatureQueryWindow`（訓練起迄與可選地點）；repository 查詢起點另含 lag/rolling lookback，禁止無界歷史掃描。lag / rolling 缺值不得以未來用電負載（`bfill`）填補，warm-up 列使用非洩漏哨兵值 `0.0`。

### 1.5 Dagster Artifact 序列化與信任邊界

- local `DATA_DIR` 與 S3 artifact 均視為讀取時的非信任位元組；檔案系統或 bucket 寫入權限不等同於可安全執行其內容。
- DataFrame artifact 使用 Parquet；非 DataFrame artifact 僅允許 JSON-compatible 值，並以 `SHIRO-JSON-V1` envelope 標記後保存。
- loader 僅接受 Parquet magic 或 `SHIRO-JSON-V1` envelope；未識別格式（包含既有未標記 pickle）必須失敗，禁止執行 pickle 反序列化。
- 既有 pickle artifact 不提供相容性載入；需重新 materialize Dagster asset 產生新的 JSON artifact。此為明確的遷移策略。

---

## 2. API 介面規格 (REST Interface)

### 2.1 健康狀態檢查

- **路徑**：`GET /health`
- **回應 Schema**：

  ```json
  {
    "status": "ok",
    "version": "0.3.0",
    "environment": "local",
    "model_loaded": true
  }
  ```

### 2.2 最新特徵快照

- **路徑**：`GET /features/latest`
- **查詢參數**：`limit`（預設 `24`）— 回傳最近 N 筆台電負載紀錄。
- **回應**：物件陣列；每筆含 `datetime`（ISO 字串）與 `load_mw` 等負載欄位。資料來源失敗時回傳 HTTP 500。

### 2.3 隨需動態視界負載預報

- **路徑**：`POST /predict`
- **請求 Body**：

  ```json
  {
    "horizon_hours": 24,
    "location": "Taipei"
  }
  ```

- **回應 Body**：

  ```json
  {
    "status": "success",
    "horizon_hours": 24,
    "location": "Taipei",
    "predictions": [
      {
        "datetime": "2026-08-22 00:00:00",
        "predicted_load_mw": 26850.4,
        "temperature": 28.5,
        "relative_humidity": 82.0
      }
    ]
  }
  ```

---

## 3. Dagster 資產排程與觸發規格

1. **`daily_training_job`**：
   - **排程**：`0 16 * * *`（每日台灣時間 00:00 執行）
   - **管線鏈路**：`raw_taipower_load_data` + `raw_weather_obs_data` $\to$ `engineered_feature_set`（`engineered_features` / `taipower_features` / `weather_features`）$\to$ `trained_forecaster_model` $\to$ `drift_monitoring_report`
   - **Feast 發布**：`taipower_features` 與 `weather_features` 透過 `feast_io_manager`（`FeastParquetIOManager`）寫入本機 `DATA_DIR` 或 `s3://{bucket}/{FEAST_S3_PREFIX}/`；特徵計算邏輯不依賴儲存目標。
2. **`hourly_drift_job`**：
   - **排程**：`0 * * * *`（每小時整點執行）
   - **管線鏈路**：獲取最新小時實際值，評估前次預測之 MAPE 與資料漂移程度。
3. **`taipower_supply_demand_snapshot_job`**：
   - **排程**：`*/10 * * * *`；抓取失敗時在同一 run 內有限次重試，不另以更高頻率輪詢。
   - **管線鏈路**：`raw_taipower_supply_demand_snapshot`、`raw_taipower_regional_supply_demand_snapshot` 與 `raw_taipower_unit_generation_snapshot` 資產擷取台電當前全台供需、各區域供需與各機組即時淨發電量並 upsert 至 TimescaleDB；三者皆不得進入 `daily_training_job` 或 `hourly_drift_job`。
   - **冪等性**：排程觸發以 tick 時間作為 `observed_at`；手動 materialize 則以實際抓取起始時間向下取整至 10 分鐘。全台快照以 `observed_at` 為鍵；區域快照以 `(observed_at, region)` 為鍵；機組快照以 `(observed_at, unit_type, unit_name)` 為鍵。相同 slot 重跑時皆更新同一快照。
   - **資料完整度與失敗政策**：
     - 全台：`curr_load` 與 `curr_util_rate` 為必填欄位；缺少、無法解析，或 HTTP／重試最終失敗時，asset 必須失敗且不得寫入快照。預估尖峰、昨日尖峰與實際最高供電能力資料組可缺少，對應 typed 欄位保存為 `NULL`，完整來源回應仍保存於 `raw_payload`。
     - 區域：來源列缺少核心 `時間`、`區域` 或 `用電(萬瓩)`、或無法解析時，略過該列且不寫入該區域快照；`發電(萬瓩)` 可缺少並保存為 `NULL`。HTTP／重試最終失敗，或成功回應中無任何有效區域列時，asset 必須失敗且不得寫入。
     - 機組：來源列缺少 `機組類型` 或 `機組名稱` 時略過該列；`淨發電量(MW)` 為 `0.0` 時仍寫入；`N/A`／`-` 的發電量、裝置容量或容量比保存為 `NULL`；備註空白保存為 `NULL`。HTTP／重試最終失敗，或成功回應中無任何有效機組列時，asset 必須失敗且不得寫入。
