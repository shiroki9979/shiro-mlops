# 系統規格與資料契約規格書 (SPEC.md)

- 建立日期：2026-08-23
- 最後更新：2026-09-14
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

### 1.2 中央氣象署資料實體 (CWA Weather Schemas)

氣象署逐時測站觀測與鄉鎮預報版本為不同資料實體，不得以單一模糊的
`location` 與時間欄位混合識別。兩者的擷取範圍皆由 allowlist 設定；預設涵蓋
臺北、臺中、高雄三個代表點。預設觀測站為臺北 `466920`、臺中 `467490`、
高雄 `467441`。

allowlist 使用單一結構化 mapping 設定，每個項目同時包含對外 alias、`station_id`
與 `geocode`，不得以兩份依賴排序的獨立清單配對。預設 mapping 對齊
`F-D0047-089`／`F-D0047-091` 縣市 `Geocode`：`Taipei: 466920 / 63000000`、
`Taichung: 467490 / 66000000`、`Kaohsiung: 467441 / 64000000`。

#### 1.2.1 氣象署逐時測站觀測

- **資料來源**：中央氣象署 OpenData API `O-A0001-001`。
- **身分契約**：以來源 `StationId` 作為穩定測站識別；測站名稱僅作顯示與跨來源映射，不參與身分判定。
- **時間契約**：以來源 `ObsTime/DateTime` 作為觀測發生時間。
- **Typed 氣象因子**：氣溫、相對濕度、測站氣壓、降水量、風速與風向；無法正規化的其他來源欄位仍保留於完整原始回應。

#### 1.2.2 氣象署鄉鎮預報版本

- **資料來源**：中央氣象署 OpenData API `F-D0047-089`（未來三日）與 `F-D0047-091`（未來一週）。
- **身分契約**：以來源 `Geocode` 作為穩定行政區識別；鄉鎮名稱僅作顯示與跨來源映射。
- **版本契約**：同一行政區與預報有效時間的不同發布版本必須並存，不得以新版覆寫舊版；資料身分至少包含資料集編號、發布時間、有效時間與 `Geocode`。
- **時間契約**：發布時間與預報有效時間分開保存，以支援 point-in-time correct 的預測重現與回測。
- **版本時間驗證**：來源未提供或無法解析 `IssueTime`／`Update` 時，ingestion 必須失敗；不得以擷取時間冒充來源版本時間。
- **Typed 氣象因子**：溫度、露點溫度、體感溫度、相對濕度、降雨機率、風速與風向；天氣現象、舒適度描述及其他來源欄位仍保留於完整原始回應。

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
  2. `raw_cwa_observation_batch`:
     - 每次逐時觀測 API 成功回應保存一筆批次 header；完整來源回應僅在此保存一次，不複製到各測站觀測列。
     - `fetched_at` (TIMESTAMPTZ, NOT NULL)：實際開始擷取時間，為批次識別。
     - `status` (VARCHAR(16), NOT NULL)：`complete` 或 `incomplete`。
     - `missing_station_ids` (JSONB, NOT NULL)：未出現在成功回應中的 allowlist 測站編號；完整批次為空陣列。
     - `raw_payload` (JSONB, NOT NULL)：完整成功回應。
     - **Constraint**: `PRIMARY KEY (fetched_at)`。
  3. `raw_cwa_station_observation`:
     - `observed_at` (TIMESTAMPTZ, NOT NULL)：來源 `ObsTime/DateTime`，寫入前轉為 UTC。
     - `station_id` (VARCHAR(16), NOT NULL)：來源 `StationId`。
     - `station_name`、`town_code`：顯示名稱與預報行政區映射資訊，不參與觀測身分判定。
     - typed 氣象欄位為 `temperature_c`、`relative_humidity_pct`、`air_pressure_hpa`、`precipitation_mm`、`wind_speed_m_s`、`wind_direction_deg`，可因來源缺值為 `NULL`。
     - **Constraint**: `PRIMARY KEY (observed_at, station_id)`；重抓同一來源觀測時更新同一筆資料。
     - **Hypertable**: `create_hypertable('raw_cwa_station_observation', 'observed_at')`。
  4. `raw_cwa_forecast_release`:
     - 每個新 `IssueTime` 保存一筆預報版本 header；完整來源回應僅在此保存一次。
     - `dataset_id` (VARCHAR(16), NOT NULL)：`F-D0047-089` 或 `F-D0047-091`。
     - `issued_at` (TIMESTAMPTZ, NOT NULL)：來源 `IssueTime`，為預報版本識別。
     - `source_updated_at` (TIMESTAMPTZ, NOT NULL)：來源 `Update`；同一發布時間的修正版以此區分。
     - `fetched_at` (TIMESTAMPTZ, NOT NULL)：首次取得此版本的時間。
     - `status`、`missing_geocodes` 與 `raw_payload` 的完整度語意同觀測批次。
     - **Constraint**: `PRIMARY KEY (dataset_id, issued_at, source_updated_at)`；每小時檢查時以此去重。
  5. `raw_cwa_township_forecast`:
     - `dataset_id` (VARCHAR(16), NOT NULL)：識別三日或一週預報產品。
     - `issued_at` (TIMESTAMPTZ, NOT NULL)：所屬預報版本發布時間。
     - `source_updated_at` (TIMESTAMPTZ, NOT NULL)：所屬來源更新時間。
     - `valid_from`、`valid_to` (TIMESTAMPTZ, NOT NULL)：預報有效區間；來源為時間點 `DataTime` 時兩者相同，來源為 `StartTime`／`EndTime` 時保留原始區間。
     - `geocode` (VARCHAR(16), NOT NULL)：來源行政區代碼；行政區名稱不參與身分判定。
     - typed 氣象欄位為 `temperature_c`、`dew_point_c`、`apparent_temperature_c`、`relative_humidity_pct`、`probability_of_precipitation_pct`、`wind_speed_m_s`、`wind_direction`，可因來源解析度或缺值為 `NULL`。
     - **Constraint**: `PRIMARY KEY (dataset_id, issued_at, source_updated_at, valid_from, valid_to, geocode)`；不同資料集與來源更新不得互相覆寫。
     - **Hypertable**: `create_hypertable('raw_cwa_township_forecast', 'valid_from')`。
  6. `raw_taipower_supply_demand_snapshot`:
     - **資料來源**：台電官方開放資料端點 `https://service.taipower.com.tw/data/opendata/apply/file/d006020/001.json`。
     - 保存台電電力供需快照，與 `raw_taipower_load` 的逐時實際負載資料分離，且不得成為既有訓練特徵的輸入。
     - `observed_at` (TIMESTAMPTZ, NOT NULL)：Dagster 排程觸發的快照觀測時間，為唯一鍵；同一排程 tick 重跑時更新同一筆快照。
     - `source_publish_time` (TIMESTAMPTZ, NULL)：來源 payload 的預估尖峰發布時間，僅作資料欄位，不參與唯一鍵。
     - 功率欄位以來源單位 `萬瓩` 保存，欄位名使用 `*_wan_kw`；使用率與備轉率使用 `*_pct`。typed 欄位包括目前用電／使用率、預估最大供電能力／尖峰用電／備轉容量／備轉率／指標／尖峰時段、昨日日期與對應尖峰供需資訊，以及實際最高供電能力與尖峰時間。
     - `raw_payload` (JSONB, NOT NULL) 保存完整成功回應；原始字串中的民國曆發布時間同時解析至 `source_publish_time`，並以 `Asia/Taipei` 解讀後寫入 UTC。
     - 永久保留歷史快照，不設定資料保留政策。
  7. `raw_taipower_regional_supply_demand_snapshot`:
     - **資料來源**：台電官方開放資料端點 `https://service.taipower.com.tw/data/opendata/apply/file/d006019/001.csv`（政府資料開放平臺資料集「今日區域別用電情況」）。
     - 保存北、中、南、東四區的區域發電量與區域用電負載成對快照，與全台 `raw_taipower_supply_demand_snapshot` 及 `raw_taipower_load` 分離，且不得成為既有訓練特徵的輸入。
     - `observed_at` (TIMESTAMPTZ, NOT NULL)：Dagster 排程觸發的快照觀測時間。
     - `region` (VARCHAR(16), NOT NULL)：來源區域名稱，正規化後為 `北部`／`中部`／`南部`／`東部`。
     - **Constraint**: `PRIMARY KEY (observed_at, region)`；同一排程 tick 重跑時更新同一區域快照。
     - `source_time` (TIMESTAMPTZ, NOT NULL)：來源 CSV `時間` 欄位（`YYYYMMDDTHHMMSS`，以 `Asia/Taipei` 解讀後寫入 UTC）。
     - 功率欄位以來源單位 `萬瓩` 保存：`generation_wan_kw`（可為 NULL）、`load_wan_kw`（必填）。
     - `raw_payload` (JSONB, NOT NULL) 保存該列來源欄位物件。
     - 永久保留歷史快照，不設定資料保留政策。
  8. `raw_taipower_unit_generation_snapshot`:
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

#### 1.3.1 CWA 既有資料遷移

- 既有 `raw_cwa_weather` 不具可信的 `StationId` provenance；建立 canonical CWA tables 後，全部既有列保留於唯讀 `legacy_cwa_weather`，不得遷入 canonical table，也不得再成為正式消費端的新資料來源。
- migration 必須保留既有資料，且可安全重跑。
- canonical typed data、batch／release 原始回應及 `legacy_cwa_weather` 均永久保留，不設定資料保留政策。

#### 1.3.2 CWA 特殊值與批次完整度

- `X` 與 `-99` 正規化為 `NULL`；降水量 `T` 與 `-98` 正規化為 `0.0 mm`；風向 `990` 正規化為 `NULL`。來源原值仍可由 batch／release 的 `raw_payload` 追溯。
- allowlist 中任一測站或行政區缺少時，以單一 transaction 寫入所有有效 child rows，將 header 標為 `incomplete`，再使 asset 失敗以觸發有限重試；重試不得產生重複觀測或預報版本。

#### 1.3.3 CWA 預報版本選取與逐時投影

- 只能選取 `issued_at <= prediction_time` 的預報版本，禁止使用預測當時尚未發布的資料。
- 每個有效小時與 typed 欄位優先採用最新可用的 `F-D0047-089`；欄位缺少或超出其涵蓋範圍時，退回最新可用的 `F-D0047-091`。
- `F-D0047-089` 的連續數值點資料在相鄰時間點間線性插值；`F-D0047-091` 的區間平均值展開為有效區間內每小時固定值；風向與文字／代碼不得線性插值。
- 可消費 `incomplete` header 中已存在的指定行政區資料；指定行政區缺少時，退回該行政區上一個完整版本。
- 預報缺少或最新 `issued_at` 超過七小時時，依序使用臺北站前日同小時觀測、同月份同小時歷史平均；月份／小時常模至少須涵蓋七個不同日期，否則視為無可用替代資料。

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
- **訓練氣象缺口**：氣溫與相對濕度只能由較早觀測 forward-fill 最多兩小時；補值後仍缺少任一必要氣象欄位的 load row 必須移除。禁止 `bfill` 與固定氣象常數。

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
    "model_loaded": true,
    "data_explorer_enabled": true
  }
  ```

- 此端點只代表 process liveness，存活時固定回傳 HTTP 200；不得因模型或資料尚未就緒而改回 503。
- `data_explorer_enabled` 表示當前 process 是否開放 Data Explorer 讀取面（`ENVIRONMENT=local` 或 `DATA_EXPLORER_ENABLED=true`）。

### 2.2 就緒狀態檢查

- **路徑**：`GET /ready`
- **語意**：模型已載入，且正常或降級氣象來源可涵蓋完整 168 小時時回傳 HTTP 200；body 必須揭露 `mode: normal` 或 `mode: degraded`。模型或必要資料不足時回傳 HTTP 503，並列出未就緒原因。
- 空資料庫首次啟動時 API process 可存活，但不得由 API lifespan 直接呼叫 CWA 或以測試資料建立正式模型。

### 2.3 隨需動態視界負載預報

- **路徑**：`POST /predict`
- **相容性欄位**：`location` 暫時保留但只接受 `Taipei`，並標示為待移除；模型仍預測全臺負載，不宣稱支援區域負載模型。
- **資料來源**：只讀 canonical TimescaleDB tables。最新可用預報發布超過七小時即視為 stale，依序退回臺北站前日同小時觀測、同月份同小時歷史平均並回傳 `status: "degraded"`；替代資料皆不存在時回傳 HTTP 503。
- **來源追溯**：每個預測點的 `weather_sources` 必須逐一揭露各氣象欄位的來源，以及可用的預報發布／更新時間；同一時點允許不同欄位來自不同產品或降級來源。
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
        "relative_humidity": 82.0,
        "weather_sources": {
          "temperature": {
            "source": "three_day",
            "issued_at": "2026-08-21T23:00:00+08:00",
            "source_updated_at": "2026-08-21T23:20:00+08:00"
          },
          "relative_humidity": {
            "source": "weekly",
            "issued_at": "2026-08-21T23:00:00+08:00",
            "source_updated_at": "2026-08-21T23:25:00+08:00"
          }
        }
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
4. **CWA 逐時測站觀測擷取工作**：
   - **排程**：`10 * * * *`（`Asia/Taipei`）；失敗時在同一 run 內最多重試兩次，每次間隔十秒。
   - **故障邊界**：使用獨立 job 與 schedule，不與台電即時快照、模型訓練或 drift 工作共用成敗狀態。
5. **CWA 鄉鎮預報版本擷取工作**：
   - **排程**：`40 * * * *`（`Asia/Taipei`）；每小時檢查 `F-D0047-089` 與 `F-D0047-091`，以 `(dataset_id, IssueTime, Update)` 去重；失敗時在同一 run 內最多重試兩次，每次間隔十秒。
   - **故障邊界**：使用獨立 job 與 schedule，不因觀測擷取或其他管線失敗而跳過當次預報版本。
6. **CWA 消費邊界**：
   - 外部 CWA API 僅由兩個 ingestion jobs 呼叫；模型訓練與線上預測一律讀取 canonical TimescaleDB tables，不得在缺資料時繞過 ingestion 邊界直接呼叫 CWA。
   - 既有模型在本階段只使用臺北站 `466920` 及其 `TownCode` 對應預報；臺中與高雄資料先完成入庫，三站加權仍由 TICKET-301 處理。
7. **本機冷啟動**：
   - 空資料庫啟動後，由操作人員依序 materialize CWA 觀測資產、CWA 預報資產與訓練工作；完成前 `/ready` 回傳 HTTP 503。
   - 不新增一次性 bootstrap sensor，也不等待每日訓練排程自然觸發。

---

## 4. 營運資料檢視器 (Data Explorer)

> **狀態：已實作。** 本節定義 [GitHub #40](https://github.com/shiroki9979/shiro-mlops/issues/40)
> 與子工單 #41–#50 的契約；`GET /data/*` 與前端 `/data` 路由僅在 local environment 或 `DATA_EXPLORER_ENABLED` 時可用。

### 4.1 產品邊界

- **主要用途**：讓營運人員確認 ingestion 是否成功、資料是否完整或過期，並檢視實際入庫內容。
- **使用者**：僅限本機或受信任內網中的工程師。
- **作業模式**：唯讀；不得透過 Data Explorer 觸發 ingestion、修改或刪除資料。
- **非目標**：不作為分析建模工具、通用資料庫管理器或公開雲端服務。

### 4.2 資料與呈現邊界

- **領域資料集**：以逐時用電負載、全台供需、區域供需、機組發電、CWA 測站觀測與 CWA 鄉鎮預報六個 canonical typed datasets 為主要檢視單位。
- **Ingestion audit**：納入 CWA 觀測批次與預報版本兩個 audit datasets，顯示狀態、擷取時間與缺少的測站或行政區；不回傳完整 `raw_payload`。
- **排除資料**：v1 不顯示完整 `raw_payload`、`legacy_cwa_weather` 歸檔與 Feast derived features。
- **呈現模型**：以領域資料集名稱、領域欄位、單位與專屬篩選條件組織介面；不將實體資料表名與任意資料庫 schema 當作使用者介面。

### 4.3 導覽與查詢行為

- **頂層導覽**：Data Explorer 使用獨立 `/data` 路由；`/monitoring` 專注於健康與新鮮度摘要，並可連結至對應資料集的篩選結果。
- **排序與分頁**：查詢預設以最新資料優先，採 server-side cursor pagination；每頁預設 50 筆、上限 200 筆，不提供無界全表載入。
- **歷史可達性**：使用者可透過有界時間範圍與 cursor 逐頁檢視所有保留中的歷史資料。
- **時間呈現**：API 回傳帶 `+08:00` offset 的 RFC 3339 timestamp；介面明示時區為 `Asia/Taipei`。
- **功率單位**：介面以 MW 為主要顯示單位；對於以萬瓩儲存的全台與區域供需 typed values，在明細或 tooltip 同時顯示儲存值，並依 `1 萬瓩 = 10 MW` 轉換。
- **預報版本**：CWA 鄉鎮預報預設顯示最新發布版本；可以 `dataset_id`、`issued_at`、`source_updated_at` 與 `geocode` 篩選所有已保存 forecast vintages。v1 不另建 Effective Serving View。

### 4.4 營運狀態語意

- **新鮮度**：每個 dataset 依自身預期更新頻率判定；超過兩個預期更新週期未取得新資料時顯示 warning。CWA forecast ingestion 新鮮度與 serving 使用的七小時 stale 規則必須分開顯示，不得混為同一狀態。
- **全台供需完整度**：每個 observation slot 預期一筆資料。
- **區域供需完整度**：每個 observation slot 預期同時具備北、中、南、東四區；缺少任一區即標記該 slot 不完整。
- **CWA 完整度**：以 allowlist 與 observation batch／forecast release audit header 判定缺少的測站或行政區。
- **逐時負載完整度**：在查詢時間區間內檢查預期的逐小時時間點，並揭露缺口。
- **機組完整度**：機組數量可變，不以固定筆數判定失敗。
- **空值語意**：資料契約允許的 nullable 欄位不得僅因為值為 `NULL` 就標記 dataset 不完整。

### 4.5 介面與 API 邊界

- **前端路由**：提供 `/data/power/load`、`/data/power/supply-demand`、`/data/power/regional`、`/data/power/units`、`/data/weather/observations`、`/data/weather/forecasts` 與 `/data/audits` nested routes，支援重新整理與 deep link。側邊欄在 Data Explorer 啟用時列出上述資料集與 CWA audits。
- **資料 API**：每個領域 dataset 使用獨立 typed read endpoint：`GET /data/power/load`、`GET /data/power/supply-demand`、`GET /data/power/regional`、`GET /data/power/units`、`GET /data/weather/observations`、`GET /data/weather/forecasts`、`GET /data/audits/cwa-observations` 與 `GET /data/audits/cwa-forecasts`。所有 list endpoints 共用 cursor pagination response envelope；不提供任意 SQL 或任意實體資料表查詢。
- **Audit 呈現**：CWA observation 與 forecast 資料頁顯示最新 audit 狀態及 Audit History 連結；`/data/audits` 提供批次歷史與 missing identifiers，但不提供完整 `raw_payload`。

### 4.6 交互與診斷行為

- **Freshness 維度**：分別顯示 ingestion age 與 source age。前者表示距上次成功入庫所經時間，後者表示最新來源事件或發布時間距今時間；不得以其中一者取代另一者。
- **資料表與明細**：列表只顯示核心營運欄位；點擊資料列後以 drawer 顯示該筆所有 typed fields。
- **篩選條件**：所有 datasets 皆提供時間區間篩選；逐時負載另提供 location，區域供需提供 region 與完整度，機組發電提供 unit type 與 unit name，測站觀測提供 station，鄉鎮預報提供有效時間、dataset、geocode 與發布／更新版本，audits 提供 audit type、status 與 missing identifier。
- **排序**：v1 固定以最新資料優先，不提供任意欄位的 server-side 排序。
- **更新**：Data Explorer 僅提供手動 Refresh 與最後取得時間；不自動改動正在檢視的歷史頁面或已展開明細。
- **CSV 匯出**：前端可將當前已載入頁面匯出為 CSV；不提供跨頁或無上限的 server-side export。
- **Monitoring 調整**：Monitoring 以 Data Source Status 摘要顯示 availability、freshness 與 completeness，並連結至 Data Explorer 對應資料集；不再提供 Feature Store Snapshot。

### 4.7 狀態、存取與失敗契約

- **Data Explorer 首頁**：`/data` 顯示全部 datasets 的最新來源時間、最新入庫時間、freshness、completeness 與明細連結。
- **狀態 API**：`GET /data/status` 是 Monitoring、Data Explorer 首頁與各資料頁的共用狀態來源。Typed list endpoints 不重複計算狀態，並共用含 `items`、`next_cursor` 與 `has_more` 的 pagination envelope。
- **狀態模型**：每個 dataset 分別回傳 `availability` (`available | empty | unavailable`)、`freshness` (`fresh | warning | unknown`)、`completeness` (`complete | incomplete | unknown`) 與衍生的 `overall` (`healthy | warning | critical | unknown`)。`unavailable` 對應 `critical`；`warning` freshness、`incomplete` 或 `empty` 對應 `warning`。
- **Cursor 契約**：cursor 為 opaque、stateless 且與當前 filters 綁定的 keyset cursor，含最後一筆排序鍵與契約版本，不設時間期限。更改 filters、契約版本不相容或 cursor 格式無效時回傳 HTTP 400。
- **開啟條件**：v1 不建立應用層登入與 RBAC。Data Explorer 路由與 API 僅在 local environment 或明確啟用功能旗標時可用；非本機存取必須由內網或 reverse proxy 限制，並使用 same-origin CORS，不得依賴現有 `CORS *` 對外暴露。
- **顯示範圍**：v1 只提供狀態、資料表、篩選、typed detail drawer 與當頁 CSV 匯出；不提供趨勢圖或可設定維度的分析視覺化。
- **HTTP 語意**：無符合資料時回傳 HTTP 200 與空 `items`；資料不完整時仍回傳 HTTP 200 並透過 domain status 揭露；無效 filter 回傳 HTTP 422；無效或不相容 cursor 回傳 HTTP 400；TimescaleDB 無法連線時回傳 HTTP 503。
- **時間範圍上限**：10 分鐘快照與機組資料單次最多查詢 7 天；逐時負載、測站觀測與 audits 最多 31 天；鄉鎮預報有效時間最多 14 天。更長歷史必須移動有界時間視窗取得。

### 4.8 交付切片

1. 建立共用 pagination／status 契約與逐時用電負載 Explorer。
2. 加入全台供需 Explorer。
3. 加入區域供需 Explorer。
4. 加入機組發電 Explorer。
5. 加入 CWA 測站觀測 Explorer。
6. 加入 CWA observation audit history。
7. 加入 CWA 鄉鎮預報 Explorer。
8. 加入 CWA forecast audit history。
9. 將 Monitoring 改為 Data Source Status 摘要。
10. 移除 Feature Store Snapshot 與 `GET /features/latest`。

每個切片皆必須同時交付 repository 查詢、typed API contract、frontend schema／query，可操作介面與對應自動化測試，不採用先完成全部 backend 後才開始 frontend 的水平切分。
