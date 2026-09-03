# 系統規格與資料契約規格書 (SPEC.md)

- 建立日期：2026-08-23
- 最後更新：2026-09-04
- 專案版本：`0.1.0`

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

---

## 2. API 介面規格 (REST Interface)

### 2.1 健康狀態檢查

- **路徑**：`GET /health`
- **回應 Schema**：

  ```json
  {
    "status": "ok",
    "version": "0.1.0",
    "environment": "local",
    "model_loaded": true
  }
  ```

### 2.2 隨需動態視界負載預報

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
   - **管線鏈路**：`raw_taipower_load_data` + `raw_weather_obs_data` $\to$ `engineered_features` $\to$ `trained_forecaster_model` $\to$ `drift_monitoring_report`
2. **`hourly_drift_job`**：
   - **排程**：`0 * * * *`（每小時整點執行）
   - **管線鏈路**：獲取最新小時實際值，評估前次預測之 MAPE 與資料漂移程度。
