# 系統規格與資料契約規格書 (SPEC.md)

- 建立日期：2026-08-23
- 最後更新：2026-09-05
- 專案版本：`0.2.0`

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

---

## 2. API 介面規格 (REST Interface)

### 2.1 健康狀態檢查

- **路徑**：`GET /health`
- **回應 Schema**：

  ```json
  {
    "status": "ok",
    "version": "0.2.0",
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
   - **管線鏈路**：`raw_taipower_supply_demand_snapshot` 資產擷取台電當前供需資訊並以 `observed_at` upsert 至 TimescaleDB。
   - **冪等性**：排程觸發以 tick 時間作為 `observed_at`；手動 materialize 則以實際抓取起始時間向下取整至 10 分鐘。兩者於相同 slot 重跑時皆更新同一快照。
   - **資料完整度與失敗政策**：`curr_load` 與 `curr_util_rate` 為必填欄位；缺少、無法解析，或 HTTP／重試最終失敗時，asset 必須失敗且不得寫入快照。預估尖峰、昨日尖峰與實際最高供電能力資料組可缺少，對應 typed 欄位保存為 `NULL`，完整來源回應仍保存於 `raw_payload`。
