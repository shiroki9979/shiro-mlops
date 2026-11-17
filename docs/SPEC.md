# 系統規格與資料契約規格書 (SPEC.md)

- 建立日期：2026-08-23
- 最後更新：2026-11-17
- 專案版本：`0.4.0`

---

## 1. 資料模型與契約 (Data Contracts)

### 1.1 台電用電負載實體 (Taipower Load Schema)

- **資料來源**：由 `raw_taipower_regional_supply_demand_snapshot` 推算之全台逐時實際負載（[ADR-0008](adr/0008-derive-hourly-actual-load-from-regional-snapshots.md)）；不使用每日尖峰負載、全台供需快照或機組淨發電量。
- **推算契約**：
  - **有效樣本**：以區域快照 `source_time` 識別；同一 `source_time` 重複擷取只計一次；北、中、南、東四區皆存在時才有效，四區 `load_wan_kw` 加總乘以 10 轉為 MW。
  - **逐時聚合**：`datetime` 為小時起點（台灣本地時間），`load_mw` 為 `[datetime, datetime + 1h)` 內有效樣本平均；有效樣本數低於 `HOURLY_LOAD_MIN_SAMPLES`（預設 `4`，每小時最多 6）時該小時缺值，不內插；未結束的小時不產出。
  - **可取得範圍**：只自開始累積區域快照時往後取得，不回補歷史。
- **預測對象**：全台逐時實際負載的預測對象識別碼固定為 `nationwide`（[ADR-0009](adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md)）。預測對象只識別負載序列本身，與天氣取自哪個氣象代表點無關。
- **欄位契約**：

| 欄位名稱 | 型態 | 單位/範例 | 說明 |
| :--- | :--- | :--- | :--- |
| `datetime` | `datetime64[ns]` | `2026-08-20 14:00:00` | 時間戳記（逐時） |
| `subject` | `str` | `nationwide` | 預測對象識別碼 |
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

allowlist 同時是氣象代表點目錄：天氣特徵與天氣解析以 alias 引用氣象代表點，
再由目錄取得其 `station_id` 與 `geocode`；測站編號與鄉鎮代碼不得寫死於目錄以外的程式碼。
動態視界預報目前使用氣象代表點 `Taipei`；引用不存在的 alias 時直接失敗。

#### 1.2.1 氣象署逐時測站觀測

- **資料來源**：中央氣象署 OpenData API `O-A0001-001`。
- **身分契約**：以來源 `StationId` 作為穩定測站識別；測站名稱僅作顯示與跨來源映射，不參與身分判定。
- **時間契約**：以來源 `ObsTime/DateTime` 作為觀測發生時間。
- **Typed 氣象因子**：氣溫、相對濕度、測站氣壓、降水量、風速與風向；無法正規化的其他來源欄位仍保留於完整原始回應。

#### 1.2.2 氣象署鄉鎮預報版本

- **資料來源**：中央氣象署 OpenData 原始檔 API `F-D0047-089`（未來三日）與 `F-D0047-091`（未來一週）。預報 ingestion 必須使用保留 `IssueTime`／`Update` 的原始 XML 檔，不得使用省略版本時間的 flattened REST 回應。
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
     - `subject` (VARCHAR(64), NOT NULL)：預測對象識別碼；全台逐時實際負載為 `nationwide`。
     - `load_mw` (DOUBLE PRECISION, NOT NULL)
     - `source` (VARCHAR(32), NOT NULL)：推算來源；目前唯一值為 `regional_snapshot_sum`。
     - `created_at` (TIMESTAMPTZ DEFAULT NOW())
     - **預測對象遷移**：ADR-0009 之前的資料庫以 `location = 'Taipei'` 保存全台負載。服務啟動時的 schema 升級在單一交易內將 `location` 改名為 `subject`，並把 `Taipei` 列改為 `nationwide`；已遷移的資料庫重跑時不改動任何列。新建資料庫直接採 `subject`。升級順序見[遷移全台負載預測對象](how-to/migrate-load-subject-to-nationwide.md)。
     - 啟用推算前須確認並清除 d015046 時期留下的資料列，不得與推算序列混用。既有資料庫升級時只補上可為 `NULL` 的 `source`，不改寫或刪除任何列；`source IS NULL` 即 d015046 時期資料列。清除與補上 `NOT NULL` 由操作人員依[移除 d015046 時期舊負載資料列](how-to/remove-legacy-d015046-load-rows.md)執行後，才開啟 `hourly_actual_load_schedule`。
     - **Constraint**: `PRIMARY KEY (time, subject)`
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
     - 保存北、中、南、東四區的區域發電量與區域用電負載成對快照，與全台 `raw_taipower_supply_demand_snapshot` 及 `raw_taipower_load` 分離，且不得直接成為訓練特徵的輸入；唯一例外為 §1.1 全台逐時實際負載推算。
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

- `X`、`-` 與 `-99` 正規化為 `NULL`；降水量 `T` 與 `-98` 正規化為 `0.0 mm`；風向 `990` 正規化為 `NULL`。來源原值仍可由 batch／release 的 `raw_payload` 追溯。
- allowlist 中任一測站或行政區缺少時，以單一 transaction 寫入所有有效 child rows，將 header 標為 `incomplete`，再使 asset 失敗以觸發有限重試；重試不得產生重複觀測或預報版本。

#### 1.3.3 CWA 預報版本選取與逐時投影

- 只能選取 `issued_at <= prediction_time` 的預報版本，禁止使用預測當時尚未發布的資料。
- 每個有效小時與 typed 欄位優先採用最新可用的 `F-D0047-089`；欄位缺少或超出其涵蓋範圍時，退回最新可用的 `F-D0047-091`。
- `F-D0047-089` 的連續數值點資料在相鄰時間點間線性插值；`F-D0047-091` 的區間平均值展開為有效區間內每小時固定值；風向與文字／代碼不得線性插值。
- 可消費 `incomplete` header 中已存在的指定行政區資料；指定行政區缺少時，退回上一個含有該行政區資料的版本，不要求該版本 `complete`。
- 預報與觀測皆取自同一氣象代表點：預報讀其 `geocode`，替代資料讀其 `station_id`。
- 預報缺少或最新 `issued_at` 超過七小時時，依序使用氣象代表點測站的前日同小時觀測、同月份同小時歷史平均；月份／小時常模至少須涵蓋七個不同日期，否則視為無可用替代資料。
- 多氣象代表點（[ADR-0012](adr/0012-combine-weather-reference-points-into-weighted-weather.md)）：每個代表點各自依上列規則選版、投影與降級，再依任務設定權重逐小時合成加權天氣。任一點降級，整次即為 `mode: degraded`；任一點連替代資料都無法涵蓋某小時，整次即無法產出（HTTP 503），不剔除該點、不重新正規化。

### 1.4 Feast 特徵庫視圖 (Feature View Schema)

- **Entity**: `location` (Join Key: `location`)；schema 凍結為動態視界預報任務專屬匯出（ADR-0009），entity 名稱不變，值為預測對象（`nationwide`）。`cwa_weather_features` 以其代表的預測對象為 entity 值，使兩個 view 可依同一 entity join。
- **Features (`taipower_load_features`)**:
  - `load_mw`: float32
  - `load_mw_lag_1`, `load_mw_lag_2`, `load_mw_lag_24`: float32
  - `load_mw_rolling_mean_6`, `load_mw_rolling_mean_24`: float32
  - `hour`, `dayofweek`, `is_weekend`, `is_day_off`: int64（`is_day_off` 依 GLOSSARY「放假日」，以 `holidays` 套件 Taiwan 曆的 `is_working_day` 判定）
  - `hour_sin`, `hour_cos`: float32
- **Features (`cwa_weather_features`)**:
  - `temperature`: float32
  - `relative_humidity`: float32
- **匯出來源**：`cwa_weather_features` 為預測對象的加權天氣（§5.3 runner 讀取觀測時合成）。Feast 凍結為動態視界預報任務專屬匯出，由 `dynamic_horizon_forecast__features` 的訓練表（§3，經 §5.3 `training_data_from_table` 還原為目標序列與觀測天氣）自行計算上列欄位，不共用任何任務的特徵配方；Feast 無正式讀取者。
- **時間正確性**：訓練資料由 runner 以明確 `as_of` 讀取 `as_of` 以前的目標序列，時間窗由已累積的目標列推導；serving 只讀負載起點往前 `lookback_hours`（§5.3）的歷史，禁止無界歷史掃描。lag 依時間戳取前 `L` 小時的負載，rolling 只統計前 `W` 小時內已有的觀測；缺漏小時不得由相鄰資料列冒充。lag / rolling 缺值不得以未來用電負載（`bfill`）填補，warm-up 列使用非洩漏哨兵值 `0.0`。
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
    "version": "0.4.0",
    "environment": "local",
    "model_loaded": true,
    "tasks": {
      "dynamic_horizon_forecast": {
        "task_type": "recursive_regression",
        "model_loaded": true
      },
      "high_load_alert": {
        "task_type": "direct_classification",
        "model_loaded": false
      },
      "load_pattern_anomaly": {
        "task_type": "unsupervised_reconstruction",
        "model_loaded": true
      }
    },
    "data_explorer_enabled": true
  }
  ```

- 此端點只代表 process liveness，存活時固定回傳 HTTP 200；不得因模型或資料尚未就緒而改回 503。
- `model_loaded` 為相容欄位，僅代表 `/predict` 所服務的動態視界預報任務模型；`tasks` 以 `task_id` 為鍵，逐一揭露每個已部署任務的任務類型與模型載入狀態。
- `data_explorer_enabled` 表示當前 process 是否開放 Data Explorer 讀取面（`ENVIRONMENT=local` 或 `DATA_EXPLORER_ENABLED=true`）。

### 2.2 就緒狀態檢查

- **路徑**：`GET /tasks/{task_id}/ready`；`GET /ready` 為動態視界預報任務 `dynamic_horizon_forecast` 的別名，回應與 `GET /tasks/dynamic_horizon_forecast/ready` 相同。
- **未知任務**：`task_id` 不在已部署任務設定中時回傳 HTTP 404。
- **回應 Body**：`status`（`ready` 或 `not_ready`）、`mode`、`model_loaded`（該任務）、`reason`。
- **語意**：模型已載入、負載起點未過舊，且預報天氣任務的正常或降級氣象來源可涵蓋完整 168 小時時回傳 HTTP 200；body 必須揭露 `mode: normal` 或 `mode: degraded`。模型或必要資料不足、或負載起點過舊時回傳 HTTP 503，並列出未就緒原因。
- **觀測天氣任務**（任務類型 `requirements().weather` 為 `OBSERVED`，例如 `load_pattern_anomaly`）：不讀預報、不降級；模型已載入、負載起點未過舊，且錨點結束小時有完整的負載與測站觀測評分窗時回傳 HTTP 200 與 `mode: normal`，否則回傳 HTTP 503。
- **負載起點過舊**：最新推算列（`source = 'regional_snapshot_sum'`）的 `raw_taipower_load.time` 早於請求時間超過任務設定 `[policies].stale_anchor_max_lag_hours`（預設 `3`）小時；此狀態不降級，`/ready` 與 `/predict` 皆回傳 HTTP 503。
- **模型**：API 啟動時依任務設定逐一載入 `DATA_DIR/models/<task_id>/`（§5.4）；單一任務的模型目錄不存在或無法載入時，只有該任務維持 `not_ready`（載入錯誤寫入日誌），其他任務照常服務。既有 `DATA_DIR/model.joblib` 不載入，首次以新格式重新訓練前 `/ready` 維持 `not_ready`。任務設定無效時 API 啟動失敗。
- 空資料庫首次啟動時 API process 可存活，但不得由 API lifespan 直接呼叫 CWA 或以測試資料建立正式模型。

### 2.3 隨需動態視界負載預報

- **路徑**：`POST /predict`（動態視界預報任務 `dynamic_horizon_forecast` 的別名，與 §2.4 共用 runner `predict_task` 與錯誤對應；預測 item 即該任務的 item（`PredictionItem`：`datetime`、`predicted_load_mw`、`temperature`、`relative_humidity`、`weather_sources`），同一請求的 `predictions` 與 `POST /tasks/dynamic_horizon_forecast/predict` 相同）
- **預測對象**：固定為 `nationwide`，並於回應 `subject` 揭露；模型只預測全台負載，不宣稱支援區域負載模型。
- **相容性欄位**：請求 `location` 為選填，於 OpenAPI 標示 `deprecated`；任何值皆被忽略，不影響預測對象，也不再回傳 HTTP 400。回應不再包含 `location`。
- **資料來源**：只讀 canonical TimescaleDB tables。負載歷史與遞迴起點只取 `source = 'regional_snapshot_sum'` 的列，`source IS NULL` 的 d015046 舊列一律忽略。氣象以請求時間為 `as_of`：只採用請求當下已發布且已更新的預報版本；最新可用預報發布早於請求時間超過七小時即視為 stale，依序退回氣象代表點測站的前日同小時觀測、同月份同小時歷史平均並回傳 `mode: "degraded"`；替代資料皆不存在，或負載起點過舊（§2.2）時回傳 HTTP 503。
- **狀態欄位**：`status` 表示請求成功（固定為 `success`）；`mode` 表示預報品質（`normal` 或 `degraded`），兩者不得混用。
- **來源追溯**：每個預測點的 `weather_sources` 依「氣象欄位 → 氣象代表點別名 → 來源」逐一揭露每個代表點的來源，以及可用的預報發布／更新時間；只有一個代表點時也採同一形狀。同一時點允許不同欄位或不同代表點來自不同產品或降級來源。
- **請求 Body**：

  ```json
  {
    "horizon_hours": 24
  }
  ```

- **回應 Body**：

  ```json
  {
    "status": "success",
    "horizon_hours": 24,
    "subject": "nationwide",
    "mode": "normal",
    "predictions": [
      {
        "datetime": "2026-08-22 00:00:00",
        "predicted_load_mw": 26850.4,
        "temperature": 28.5,
        "relative_humidity": 82.0,
        "weather_sources": {
          "temperature": {
            "Taipei": {
              "source": "three_day",
              "issued_at": "2026-08-21T23:00:00+08:00",
              "source_updated_at": "2026-08-21T23:20:00+08:00"
            }
          },
          "relative_humidity": {
            "Taipei": {
              "source": "weekly",
              "issued_at": "2026-08-21T23:00:00+08:00",
              "source_updated_at": "2026-08-21T23:25:00+08:00"
            }
          }
        }
      }
    ]
  }
  ```

### 2.4 通用任務推論

- **路徑**：`POST /tasks/{task_id}/predict`（ADR-0009）
- **請求 Body**：`horizon_hours`（整數 1–168，預設 24）；不接受 `location`。語意依任務的天氣輸入而定：
  - 預報天氣任務（`FORECAST`）：負載起點之後預測的小時數（預測視界）。
  - 觀測天氣任務（`OBSERVED`）：評分最近幾個時間窗結束小時，由負載起點往回算，即結束小時落在 `(anchor - horizon_hours, anchor]`；不預測未來。資料有缺口的時間窗不評分，因此回傳筆數可能少於 `horizon_hours`，但不以常數補值。
- **回應 Body**：共通欄位 `status`（固定為 `success`）、`task_id`、`task_type`、`subject`、`mode`，以及 `predictions`；`predictions` 的 item schema 由任務類型的 `prediction_item` 與任務設定的 `weather.fields` 共同決定（§5.2），OpenAPI 以每個任務的 `<TaskId>TaskPredictionResponse`（item 為 `<TaskId>PredictionItem`，未附帶天氣者直接沿用任務類型的 item）逐一描述，並以 `task_id` 常數區分；回應模型於建構時驗證，端點不再以聯集重驗。
- **Item 組成**：runner 回傳的預測列、天氣列（`weather.fields`）與 `weather_sources` 依位置一一對應合併後，以該任務的 item 驗證；`datetime` 以字串輸出（`YYYY-MM-DD HH:MM:SS`）。觀測天氣任務的天氣列與來源由 runner 對齊至被評分的結束小時（該小時以前最新一筆測站觀測，每個代表點的來源為 `{"source": "station_observation", "observed_at": ...}`），因此依位置合併的契約同樣成立。
- **錯誤對應**：

  | 情境 | HTTP |
  | :--- | :--- |
  | `task_id` 不在已部署任務設定中 | 404 |
  | 該任務模型未載入 | 503 |
  | `TaskUnavailableError`（`MissingLoadHistoryError`、`StaleLoadAnchorError`、`InsufficientLoadHistoryError`、`WeatherUnavailableError`、`ObservedInputsIncompleteError`）或 `TaskNotReady` | 503 |
  | 持久層不可用（SQLAlchemy 錯誤） | 503 |
  | 其他預測錯誤 | 500 |

- **回應範例**（`dynamic_horizon_forecast`）：

  ```json
  {
    "status": "success",
    "task_id": "dynamic_horizon_forecast",
    "task_type": "recursive_regression",
    "subject": "nationwide",
    "mode": "normal",
    "predictions": [
      {
        "datetime": "2026-08-22 00:00:00",
        "predicted_load_mw": 26850.4,
        "temperature": 28.5,
        "relative_humidity": 82.0,
        "weather_sources": {"temperature": {"Taipei": {"source": "three_day"}}}
      }
    ]
  }
  ```

- **回應範例**（`high_load_alert`）：每個預報小時一個 item，`is_high_load` 為 `probability >= 0.5`，`threshold_mw` 為該次預警錨點的高負載門檻（同一回應內各 item 相同）。

  ```json
  {
    "status": "success",
    "task_id": "high_load_alert",
    "task_type": "direct_classification",
    "subject": "nationwide",
    "mode": "normal",
    "predictions": [
      {
        "datetime": "2026-08-22 14:00:00",
        "is_high_load": true,
        "probability": 0.83,
        "threshold_mw": 38210.5,
        "temperature": 33.1,
        "relative_humidity": 62.0,
        "weather_sources": {"temperature": {"Taipei": {"source": "three_day"}}}
      }
    ]
  }
  ```

- **回應範例**（`load_pattern_anomaly`，請求 `{"horizon_hours": 2}`，負載起點 `2026-08-22 00:00`）：

  ```json
  {
    "status": "success",
    "task_id": "load_pattern_anomaly",
    "task_type": "unsupervised_reconstruction",
    "subject": "nationwide",
    "mode": "normal",
    "predictions": [
      {"datetime": "2026-08-21 23:00:00", "anomaly_score": 0.41, "is_anomaly": false, "threshold": 1.27},
      {"datetime": "2026-08-22 00:00:00", "anomaly_score": 3.85, "is_anomaly": true, "threshold": 1.27}
    ]
  }
  ```

---

## 3. Dagster 資產排程與觸發規格

1. **任務資產工廠（`pipelines/task_pipelines.py`）**：
   - **生成規則**：Dagster code location 載入時，依 `deployed_tasks()` 為每份任務設定（§5.1）產生下列定義；新增一份任務設定即新增一組，不需改動程式。名稱以 `__` 分隔任務 id 與後綴，資產 group 為 `task_id`。

     | 種類 | 名稱 | 內容 |
     | :--- | :--- | :--- |
     | 資產 | `{task_id}__features` | 經 runner `load_training_data` 讀取並套用 §3.1 最低累積，輸出 `training_table`（以目標序列與觀測天氣的時間軸聯集為主鍵序列化：`datetime`、`subject`、`load_mw` 與 `weather.fields`，保留負載缺漏小時的觀測天氣；`rows` metadata 為訓練表總列數）；lineage 依賴 `raw_taipower_load` 與 `raw_cwa_station_observation`，但不執行它們 |
     | 資產 | `{task_id}__model` | 以 `training_data_from_table` 還原上游訓練表後經 `fit_task` 訓練，不再重讀資料庫；模型存入 `DATA_DIR/models/{task_id}/`，並寫入 MLflow（見下）。輸出 `task_id`、`metrics`、`run_id`、`model_version`、`model_path`、`training_rows` |
     | 資產 | `{task_id}__monitoring` | 經 runner `monitor_task` 以有界查詢讀取有效逐時觀測數與 `as_of` 以前最新一列（僅 `source = 'regional_snapshot_sum'`），再由任務類型 `assess_health` 以任務設定 `[health]` 門檻判定；輸出 `task_id`、`status`（`HEALTHY`／`WARNING`）、`health_reason`、`metrics`、`training_rows`、`target_hours`（有效逐時目標觀測數）、`latest_target_time`、`latest_target_value`（目前任務的目標皆為逐時實際負載，單位 MW） |
     | job | `{task_id}__training_job` | selection 為 `{task_id}__features` 及其所有下游（model、monitoring，以及只掛在該任務的資產，例如 Feast 匯出） |
     | job | `{task_id}__monitoring_job` | selection 僅含 `{task_id}__monitoring`；model 輸出取自最近一次訓練的 I/O Manager 產物，不重跑讀取完整歷史的 features |
     | 排程 | `{task_id}__training_schedule` | cron 取自 `[schedule].training`，時區 `Asia/Taipei`；§3.1 最低累積未達時以 `SkipReason` 揭露差距 |
     | 排程 | `{task_id}__monitoring_schedule` | cron 取自 `[schedule].monitoring`，時區 `Asia/Taipei`；除最低累積外，另需 `{task_id}__model` 已有 materialization |

   - **邊界**：擷取資產（台電快照、逐時負載推算、CWA 觀測與預報）以資料來源為中心、跨任務共用，不隨任務生成；任務的兩個 job 皆不得選取任何擷取資產。資產只經 runner（§5.3）取門檻、資料、訓練與監控結果。
   - **排程 run_key**：排程 tick 轉為台灣本地時間 ISO 字串作為 `run_key`，同一 tick 重複評估不重跑；無 tick 的手動評估不帶 `run_key`。
   - **MLflow**：每個任務擁有獨立 experiment 與 registered model，名稱皆等於 `task_id`。每次訓練以 `{task_id}_training` 為 run 名稱記錄 metrics、攤平的 `[params]`（巢狀鍵以 `.` 連接，另含 `task_id`、`task_type`）與模型目錄（artifact path `model`），並以該 artifact URI 建立新的 model version（模型為原生檔案而非 MLflow logged model，ADR-0010）。MLflow 不可用時記錄警告、`run_id` 標為 `local_run`，已保存的模型仍有效。
   - **動態視界預報任務**：`dynamic_horizon_forecast__training_schedule` 為 `0 0 * * *`（`Asia/Taipei`，與舊版 `0 16 * * *` UTC 同一時刻），`dynamic_horizon_forecast__monitoring_schedule` 為 `0 * * * *`；健康門檻 `max_mape = 10.0`。
   - **高負載預警任務**：`high_load_alert__training_schedule` 為 `30 0 * * *`（錯開動態視界預報 00:00 與用電型態異常偵測 01:00 的訓練），`high_load_alert__monitoring_schedule` 為 `5 * * * *`；健康門檻 `min_precision`／`min_recall`／`min_f1` 皆為 `0.5`。
   - **用電型態異常偵測任務**：`load_pattern_anomaly__training_schedule` 為 `0 1 * * *`（錯開前兩項任務的訓練）、`load_pattern_anomaly__monitoring_schedule` 為 `0 * * * *`（皆 `Asia/Taipei`）；MLflow metrics 含合成異常召回率與乾淨資料誤報率（§5.2）；健康門檻 `min_recall = 0.8`、`max_false_positive_rate = 0.05`。
   - **Feast 發布**：`dynamic_horizon_forecast_feast_export`（輸出 `taipower_features` 與 `weather_features`）只以 `dynamic_horizon_forecast__features` 為輸入，因此只在該任務的訓練 job 中執行；天氣匯出只含訓練表中有觀測值的小時。兩者透過 `feast_io_manager`（`FeastParquetIOManager`）寫入本機 `DATA_DIR` 或 `s3://{bucket}/{FEAST_S3_PREFIX}/`；特徵計算邏輯不依賴儲存目標。
   - **更名遷移**：舊版的 `daily_training_job`／`hourly_drift_job`、其排程，以及資產 `taipower_load_feature_source`、`cwa_observation_feature_source`、`engineered_features`、`trained_forecaster_model`、`drift_monitoring_report` 已移除。Dagster 不會把舊資產鍵的 materialization 歷史轉移到新鍵：監控排程只認 `{task_id}__model`，部署後須先成功執行一次 `{task_id}__training_job`。新排程預設為停用，須在 Dagster UI 開啟。舊的單一 MLflow experiment（`MLFLOW_EXPERIMENT_NAME`）不再使用，既有 run 保留但不再增加。
   - **最低累積（§3.1，訓練與監控共用）**：
     - `raw_taipower_load` 有效逐時觀測少於任務設定 `[policies].min_training_hours`（動態視界預報任務為 `672`，即 28 日；高負載預警任務為 `1344`，即 56 日）時，訓練與監控必須明確失敗或略過並揭露原因，不得以不足資料產出模型或報告。有效逐時觀測指 `source = 'regional_snapshot_sum'` 的列；存在 `source IS NULL` 的舊列時視為未就緒。
     - 排程 tick 以 `SkipReason` 揭露差距；runner 拋出領域錯誤 `TaskNotReady`，手動執行時由 `{task_id}__features` 或 `{task_id}__monitoring` 轉為 Dagster `Failure` 並附 `valid_hours`／`required_hours`／`legacy_rows` metadata。
2. **`taipower_supply_demand_snapshot_job`**：
   - **排程**：`*/10 * * * *`；抓取失敗時在同一 run 內有限次重試，不另以更高頻率輪詢。全台與機組快照最多重試兩次、每次間隔十秒；區域快照為全台逐時實際負載的唯一來源且無法回補，最多重試三次，以十秒起算指數退避（依序等待 10、30、70 秒，約 110 秒內結束）。
   - **管線鏈路**：`raw_taipower_supply_demand_snapshot`、`raw_taipower_regional_supply_demand_snapshot` 與 `raw_taipower_unit_generation_snapshot` 資產擷取台電當前全台供需、各區域供需與各機組即時淨發電量並 upsert 至 TimescaleDB；三者皆不得進入任何任務的 `{task_id}__training_job` 或 `{task_id}__monitoring_job`；區域快照僅能經由 `hourly_actual_load_job` 推算後間接供訓練使用。
   - **冪等性**：排程觸發以 tick 時間作為 `observed_at`；手動 materialize 則以實際抓取起始時間向下取整至 10 分鐘。全台快照以 `observed_at` 為鍵；區域快照以 `(observed_at, region)` 為鍵；機組快照以 `(observed_at, unit_type, unit_name)` 為鍵。相同 slot 重跑時皆更新同一快照。
   - **資料完整度與失敗政策**：
     - 全台：`curr_load` 與 `curr_util_rate` 為必填欄位；缺少、無法解析，或 HTTP／重試最終失敗時，asset 必須失敗且不得寫入快照。預估尖峰、昨日尖峰與實際最高供電能力資料組可缺少，對應 typed 欄位保存為 `NULL`，完整來源回應仍保存於 `raw_payload`。
     - 區域：來源列缺少核心 `時間`、`區域` 或 `用電(萬瓩)`、或無法解析時，略過該列且不寫入該區域快照；`發電(萬瓩)` 可缺少並保存為 `NULL`。HTTP／重試最終失敗，或成功回應中無任何有效區域列時，asset 必須失敗且不得寫入。
     - 機組：來源列缺少 `機組類型` 或 `機組名稱` 時略過該列；`淨發電量(MW)` 為 `0.0` 時仍寫入；`N/A`／`-` 的發電量、裝置容量或容量比保存為 `NULL`；備註空白保存為 `NULL`。HTTP／重試最終失敗，或成功回應中無任何有效機組列時，asset 必須失敗且不得寫入。
3. **CWA 逐時測站觀測擷取工作**：
   - **排程**：`10 * * * *`（`Asia/Taipei`）；失敗時在同一 run 內最多重試三次，以三十秒起算指數退避（Dagster 依序等待 30／90／210 秒，約 5.5 分鐘內結束）；重試用盡時 run 必須失敗且不得改動既有資料。
   - **故障邊界**：使用獨立 job 與 schedule，不與台電即時快照、任務訓練或監控工作共用成敗狀態。
4. **CWA 鄉鎮預報版本擷取工作**：
   - **排程**：`40 * * * *`（`Asia/Taipei`）；每小時檢查 `F-D0047-089` 與 `F-D0047-091`，以 `(dataset_id, IssueTime, Update)` 去重；失敗時在同一 run 內最多重試三次，以三十秒起算指數退避；重試用盡時 run 必須失敗且不得改動既有預報版本。
   - **故障邊界**：使用獨立 job 與 schedule，不因觀測擷取或其他管線失敗而跳過當次預報版本。
5. **`hourly_actual_load_job`**：
   - **排程**：`5 * * * *`（`Asia/Taipei`）。
   - **管線鏈路**：讀取 `raw_taipower_regional_supply_demand_snapshot`，依 §1.1 推算已結束小時，以 `(time, subject)` upsert 至 `raw_taipower_load`，`subject` 為 `nationwide`；不呼叫任何台電外部 API。
   - **推算窗口**：最近 `HOURLY_LOAD_RECOMPUTE_HOURS`（預設 `3`）個已結束小時，並向前延伸至 tick 時已存在的最後一個推算小時（`source = regional_snapshot_sum`）之後，使擷取中斷前已入庫、尚未推算的小時在排程恢復後補上；最多回溯 `HOURLY_LOAD_CATCHUP_MAX_HOURS`（預設 `168`）個小時，尚無推算小時時即回溯此上限。超出上限而未涵蓋的區間以 warning 記錄於 run log，改由 `scripts/rederive_hourly_actual_load.py` 補算。
   - **冪等性**：排程以 tick 時間決定重算窗口，手動 materialize 以實際執行時間決定；重算同一小時得到相同結果；後到的有效樣本可使先前缺值的小時補上或更新平均值。
6. **CWA 消費邊界**：
   - 外部 CWA API 僅由兩個 ingestion jobs 呼叫；模型訓練與線上預測一律讀取 canonical TimescaleDB tables，不得在缺資料時繞過 ingestion 邊界直接呼叫 CWA。
   - 三個任務目前只使用氣象代表點 `Taipei`（測站與預報區見 §1.2 目錄）。任務設定可依 §5.1 列出多個加權代表點（ADR-0012），是否採用由 TICKET-303 的滾動起點回測判定。
7. **本機冷啟動**：
   - 空資料庫啟動後，台電即時快照排程須先累積區域快照，且 `hourly_actual_load_job` 產出的有效逐時觀測達 §3 訓練最低累積；之後由操作人員依序 materialize CWA 觀測資產、CWA 預報資產與訓練工作；完成前 `/ready` 回傳 HTTP 503。
   - 不新增一次性 bootstrap sensor，也不等待每日訓練排程自然觸發。
   - 操作人員以 `python -m shiro_mlops.pipelines.smoke_check`（`make smoke-check`）在 Dagster 容器內檢查排程註冊與啟用狀態（任務排程的期望 cron 由任務設定推導）、各任務訓練與監控 job 的 selection 邊界，以及每個任務的累積進度（`{task_id} load accumulation`）、新鮮度（`{task_id} load freshness`）與兩個任務排程下一次 tick 的結果；此檢查唯讀，不啟動 run。操作步驟見 [冷啟動恢復指南](how-to/recover-training-after-load-cold-start.md)。

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
- **逐時負載檢視口徑**：列表、缺口與狀態僅讀取 `source = 'regional_snapshot_sum'` 的推算列；升級期間尚未清除的 d015046 舊列不得出現在 canonical 檢視或影響新鮮度與完整度。
- **Ingestion audit**：納入 CWA 觀測批次與預報版本兩個 audit datasets，顯示狀態、擷取時間與缺少的測站或行政區；不回傳完整 `raw_payload`。
- **排除資料**：v1 不顯示完整 `raw_payload`、`legacy_cwa_weather` 歸檔與 Feast derived features。
- **呈現模型**：以領域資料集名稱、領域欄位、單位與專屬篩選條件組織介面；不將實體資料表名與任意資料庫 schema 當作使用者介面。

### 4.3 導覽與查詢行為

- **頂層導覽**：Data Explorer 使用獨立 `/data` 路由；`/monitoring` 專注於健康與新鮮度摘要，並可連結至對應資料集的篩選結果。
- **排序與分頁**：八個列表以各資料集固定的完整複合鍵降冪排序，使用 v2 server-side keyset cursor；排序、翻頁比較與 cursor 均保留原始微秒精度。每頁預設 50 筆、上限 200 筆，不提供無界全表載入。
- **時間窗口**：列表與完整度查詢共用精確閉區間 `[start, end]`；兩端點納入、窗口外一微秒排除，`start = end` 合法。cursor 固定第一次解析的窗口，頁面顯示時間維持既有整秒格式。
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
- **篩選條件**：所有 datasets 皆提供時間區間篩選；逐時負載另提供預測對象（`subject`，如 `nationwide`），區域供需提供 region 與完整度，機組發電提供 unit type 與 unit name，測站觀測提供 station，鄉鎮預報提供有效時間、dataset、geocode 與發布／更新版本，audits 提供 audit type、status 與 missing identifier。
- **預設窗口與 cursor 失效**：URL 未指定 `start`／`end` 時，前端以進入頁面當下計算預設窗口，同一次瀏覽內不隨重新繪製漂移，且不主動寫入 URL。變更窗口或任一篩選即清除 cursor 並回到第一頁；只有翻頁操作會設定 cursor。
- **排序**：v1 固定以最新資料優先，不提供任意欄位的 server-side 排序。
- **更新**：Data Explorer 僅提供手動 Refresh 與最後取得時間；不自動改動正在檢視的歷史頁面或已展開明細。
- **CSV 匯出**：前端可將當前已載入頁面匯出為 CSV；不提供跨頁或無上限的 server-side export。
- **Monitoring 調整**：Monitoring 以 Data Source Status 摘要顯示 availability、freshness 與 completeness，並連結至 Data Explorer 對應資料集；不再提供 Feature Store Snapshot。

### 4.7 狀態、存取與失敗契約

- **Data Explorer 首頁**：`/data` 顯示全部 datasets 的最新來源時間、最新入庫時間、freshness、completeness 與明細連結。
- **狀態 API**：`GET /data/status` 是 Monitoring、Data Explorer 首頁與各資料頁的共用狀態來源。Typed list endpoints 不重複計算狀態，並共用含 `items`、`next_cursor` 與 `has_more` 的 pagination envelope。
- **狀態模型**：每個 dataset 分別回傳 `availability` (`available | empty | unavailable`)、`freshness` (`fresh | warning | unknown`)、`completeness` (`complete | incomplete | unknown`) 與衍生的 `overall` (`healthy | warning | critical | unknown`)。`unavailable` 對應 `critical`；`warning` freshness、`incomplete` 或 `empty` 對應 `warning`。
- **Cursor 契約**：八個列表只接受 v2 cursor。cursor 為 opaque、stateless 且與當前窗口及 filters 綁定的 keyset cursor，含最後一筆完整原始排序鍵與契約版本，不設時間期限。更改 filters、v1 或格式無效時回傳 HTTP 400。帶 cursor 的請求收到 400 時，前端顯示返回第一頁的恢復操作（字典鍵 `explorer.results.backToFirstPage`，顯示文字隨介面語系）；使用者點擊後清除 cursor，保留窗口與篩選。明確預報版本保留，隱含最新版本重新解析；422／503 不提供此恢復操作。
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

---

## 5. ML 任務設定與任務類型介面

> 依 [ADR-0009](adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md) 與 [ADR-0010](adr/0010-persist-models-in-native-non-executable-formats.md)。程式位於 `src/shiro_mlops/tasks/`，任務設定檔與程式一同隨映像檔發布。

### 5.1 任務設定 Schema（`tasks/<task_id>.toml`）

以標準函式庫 `tomllib` 讀取，兩階段 Pydantic 驗證：先驗證共通欄位，再以任務類型的 `params_model` 驗證 `[params]`、`health_model` 驗證 `[health]`。Dagster code location 載入與 API 啟動時即載入全部任務設定；任何錯誤皆拋出 `TaskDefinitionError(path, detail)`，`detail` 指出欄位路徑（如 `policies.stale_anchor_max_lag_hours`、`params.rolling_windows`）。未知欄位一律拒絕。

| 欄位 | 型別 | 規則 |
| :--- | :--- | :--- |
| `task_id` | string | 小寫英數與底線；必須等於檔名（不含 `.toml`） |
| `task_type` | string | 必須為已註冊的任務類型（§5.2） |
| `subject` | string | 預測對象識別碼，例如 `nationwide` |
| `target` | `"hourly_actual_load"` | 目標序列來源；目前只有全台逐時實際負載（`raw_taipower_load`，`source = 'regional_snapshot_sum'`） |
| `weather.reference_points` | list[string] | 必須引用 CWA 擷取目錄中的 alias，不得重複 |
| `weather.weights` | list[float] | 與 `reference_points` 一一對應的權重，每個大於 0、總和為 1（容許 `1e-6` 浮點誤差）；只有一個代表點時可省略（權重為 1），多個代表點時必填 |
| `weather.fields` | list[`temperature` \| `relative_humidity`] | 訓練觀測與預報皆提供的氣象欄位 |
| `policies.min_training_hours` | 正整數 | 最低累積門檻（§3.1） |
| `policies.stale_anchor_max_lag_hours` | 正整數 | 負載起點過舊門檻（§2.2） |
| `policies.validation_fraction` | 0 < x < 1 | 依時間切分的驗證比例 |
| `params` | table | 依任務類型驗證；為特徵配方與模型超參數的唯一來源 |
| `schedule.training` | cron string | 訓練排程（`Asia/Taipei`，§3）；五個欄位，只接受數字、`*`、範圍、步進與逗號清單，超出欄位範圍即拒絕 |
| `schedule.monitoring` | cron string | 監控排程（`Asia/Taipei`，§3）；規則同上 |
| `health` | table | 依任務類型的 `health_model` 驗證；健康判定門檻的唯一來源 |

`recursive_regression` 的 `[params]`：`lags`（正整數 list，至少一個）、`rolling_windows`（正整數 list，至少一個）、`day_off`（布林，預設 `false`；開啟時加入以各小時日期判定的 `is_day_off`）、`[params.model]` 的 `n_estimators`（正整數）、`learning_rate`（正數）、`num_leaves`（≥ 2）；objective、metric 與 random seed 由任務類型固定。`[health]`：`max_mape`（正數，單位 %）。

`direct_classification` 的 `[params]`：`lags`、`rolling_windows`（規則同上，但皆相對於錨點）、`day_off`（布林，預設 `false`；開啟時加入以目標小時日期判定的 `is_day_off`）、`[params.threshold]` 的 `window_days`（正整數）與 `quantile`（0 < x < 1）、`[params.model]`（同上）；objective（`binary`）與 random seed 由任務類型固定。`[health]`：`min_precision`、`min_recall`、`min_f1`（皆為 0–1）。

`unsupervised_reconstruction` 的 `[params]`：`window_hours`（整數 ≥ 6，時間窗長度）、`threshold_quantile`（0 < x < 1，判定門檻取驗證期校準日重建誤差的分位數）、`[params.model]` 的 `hidden_layer_sizes`（一至三個正整數，淺層）、`alpha`（≥ 0）、`learning_rate_init`（正數）、`max_iter`（正整數）；激活函數（隱藏層 `relu`、輸出層 `identity`）、solver `adam` 與 random seed 由任務類型固定。`[health]`：`min_recall`（0 < x ≤ 1）、`max_false_positive_rate`（0 ≤ x < 1）。

動態視界預報任務設定 `tasks/dynamic_horizon_forecast.toml`：`subject = "nationwide"`、氣象代表點 `Taipei`、`min_training_hours = 672`、`stale_anchor_max_lag_hours = 3`、`validation_fraction = 0.2`、`lags = [1, 2, 24, 48, 168]`、`rolling_windows = [6, 24]`、LightGBM `n_estimators = 100`、`learning_rate = 0.05`、`num_leaves = 31`、`[schedule]` `training = "0 0 * * *"`／`monitoring = "0 * * * *"`、`[health]` `max_mape = 10.0`。

高負載預警任務設定 `tasks/high_load_alert.toml`：`task_type = "direct_classification"`、`subject = "nationwide"`、氣象代表點 `Taipei`、`min_training_hours = 1344`、`stale_anchor_max_lag_hours = 3`、`validation_fraction = 0.2`、`lags = [1, 2, 24, 168]`、`rolling_windows = [6, 24]`、`threshold.window_days = 28`、`threshold.quantile = 0.9`、LightGBM `n_estimators = 200`、`learning_rate = 0.05`、`num_leaves = 31`、`[schedule]` `training = "30 0 * * *"`／`monitoring = "5 * * * *"`、`[health]` `min_precision = 0.5`、`min_recall = 0.5`、`min_f1 = 0.5`。每一筆訓練標籤之前都需要完整的 28 日門檻窗（672 小時），再加上 672 小時的訓練列，故最低累積為 1344 小時；依目前推算逐時負載的累積進度估算，最早約於 2026-11-21 可訓練；缺值小時不計入，會使日期再往後。

用電型態異常偵測任務設定 `tasks/load_pattern_anomaly.toml`：`task_type = "unsupervised_reconstruction"`、`subject = "nationwide"`、氣象代表點 `Taipei`（`temperature`、`relative_humidity`）、`min_training_hours = 672`、`stale_anchor_max_lag_hours = 3`、`validation_fraction = 0.2`、`window_hours = 24`、`threshold_quantile = 0.99`、`hidden_layer_sizes = [32, 8, 32]`、`alpha = 0.0001`、`learning_rate_init = 0.001`、`max_iter = 500`、`[schedule]` `training = "0 1 * * *"`／`monitoring = "0 * * * *"`、`[health]` `min_recall = 0.8`、`max_false_positive_rate = 0.05`。

### 5.2 任務類型介面（`tasks/types/`）

任務類型為純計算 adapter，不接觸 repository；以 `tasks/types/__init__.py` 的明確 registry（`TASK_TYPES`、`get_task_type(name)`）依名稱對應。

- `name`、`params_model`：registry 名稱與 `[params]` 的 Pydantic model。
- `prediction_item`：`POST /tasks/{task_id}/predict` 單一預測 item 中任務類型自身欄位的 Pydantic model（§2.4），欄位取自 `TaskModel.predict` 輸出，其餘欄位忽略。繼承 `WeatherEchoingItem` 者，服務層另補上任務設定 `weather.fields` 的每個天氣欄位（`float`）與 `weather_sources`，因此 item 的天氣欄位跟隨任務設定，任務類型不寫死天氣欄位。
- `requirements(params) -> InputRequirements(weather, lookback_hours, history_coverage)`：預測時使用預報（`FORECAST`）或觀測（`OBSERVED`）天氣，以及 runner 有界讀取歷史所需的小時數。`history_coverage`（選填，`HistoryCoverage(window_hours, min_valid_hours)`）要求錨點往前 `window_hours`（`(anchor - window_hours, anchor]`）內至少 `min_valid_hours` 個有實際負載的小時；不足時 runner 拋出 `InsufficientLoadHistoryError`，`/tasks/{task_id}/ready` 與 predict 皆回 503，任務類型不會收到歷史不足的 `PredictionData`。
- `train(params, TrainingData) -> Trained(model, metrics)`：負責特徵、標籤、fit 與評估。`TrainingData` 含 `load`（`datetime`、`subject`、`load_mw`）、`weather`（`datetime` 與 `weather.fields`，一律為觀測天氣）與 `validation_start`；target 時間 `>= validation_start` 者為驗證列，任務類型不得自行切分。
- `health_model`、`assess_health(thresholds, metrics) -> HealthAssessment(status, reason)`：健康判定規則屬於任務類型，門檻來自任務設定 `[health]`；`status` 為 `HealthStatus.HEALTHY` 或 `WARNING`，`reason` 指出決定判定的指標與門檻。缺少判定所需指標時必須回報 `WARNING`，不得視為健康。
- `load(directory) -> TaskModel`；`TaskModel.predict(PredictionData) -> DataFrame`、`TaskModel.save(directory)`。`PredictionData` 含 `anchor`、`load_history`、`weather`、`horizon_hours`，交付時已保證負載起點新鮮且天氣欄位完整，任務類型不得以常數補值。`FORECAST` 任務的 `weather` 為錨點之後的預報（或降級來源）；`OBSERVED` 任務的 `weather` 為 `[anchor - lookback_hours, anchor]` 內的測站觀測，`horizon_hours` 表示評分最近幾個結束小時（§2.4），`None` 表示評分 `load_history` 內所有完整時間窗。

已註冊任務類型：

- `recursive_regression`：LightGBM 單步模型遞迴展開（ADR-0003 僅適用此類型）；`lookback_hours = max(lags, rolling_windows)`；預測輸出 `datetime`、`predicted_load_mw`；`prediction_item` 為 `RecursiveRegressionPrediction`（`datetime`、`predicted_load_mw`，附帶天氣）；動態視界預報任務的 item 因任務設定宣告 `temperature` 與 `relative_humidity`，與 `/predict` 的 `PredictionItem` 相同；評估為驗證列上的 one-step-ahead MAPE／RMSE／MAE；驗證列為空時不回報任何指標（不得以 `0.0` 佔位），健康判定因缺少 `mape` 而為 `WARNING`。健康判定：驗證期 `mape < max_mape` 為 `HEALTHY`，否則 `WARNING`。
- `direct_classification`：直接策略二元分類（高負載預警）。每個錨點（有實際負載的小時）與領先時數 `k = 1..168` 組成一列：特徵為錨點當下已知的 `anchor_load_mw`、`load_mw_lag_{L}`（錨點前 `L` 小時的負載）、`load_mw_rolling_mean_{W}`／`load_mw_rolling_std_{W}`（含錨點的前 `W` 小時）與 `threshold_mw`，目標小時的日曆特徵與天氣，以及 `lead_hours = k`；單一 `LGBMClassifier` 涵蓋整個視界，不串接任何預報輸出。高負載門檻 `threshold_mw` 為區間 `(anchor - window_days, anchor]` 內全台逐時實際負載的 `quantile` 分位數（線性內插），只使用錨點當下已知的資料；門檻窗內缺少任一小時的實際負載（28 日須完整 672 小時）時，該錨點不產生門檻與訓練列。`requirements()` 以同一規則宣告 `history_coverage`，預測時歷史不足由 runner 回報不可用（503）。標籤為目標小時實際負載 `>` 錨點門檻；觀測天氣缺漏的目標小時直接捨棄。訓練標籤只有單一類別時拒絕訓練。`lookback_hours = window_days × 24 + max(lags, rolling_windows)`。預測輸出與天氣列逐列對齊（每個預報小時一列、順序相同）：`datetime`、`is_high_load`（`probability >= 0.5`）、`probability`、`threshold_mw`；目標小時超出領先 1–168 小時時拋出錯誤。`prediction_item` 為 `DirectClassificationPrediction`（`datetime`、`is_high_load`、`probability`、`threshold_mw`，附帶天氣），item 另含任務 `weather.fields` 的天氣欄位與 `weather_sources`。評估為驗證列（目標小時 `>= validation_start`）上以 0.5 為界的 precision／recall／F1；驗證列為空時不回報任何指標，健康判定因缺少指標而為 `WARNING`。健康判定：三項指標皆 `>=` 各自的 `min_*` 為 `HEALTHY`；任一不足或缺少即 `WARNING`。
- `unsupervised_reconstruction`：淺層 MLP AutoEncoder（sklearn `MLPRegressor`，以輸入重建輸入）對滑動窗評分，偵測用電型態異常；訓練不需標籤。
  - **輸入**：`requirements()` 為 `OBSERVED` 天氣，`lookback_hours = window_hours + 168`，足以為最多 168 個結束小時各組一個完整時間窗。每個時間窗為結束小時（含）往前 `window_hours` 個連續小時：逐時全台實際負載、逐時 `weather.fields` 測站觀測、逐時週末旗標，加上結束小時的 hour-of-day 與 day-of-week sin/cos 編碼。觀測天氣最多向前補兩小時；負載缺小時或天氣缺口更長的時間窗不訓練也不評分。各特徵以訓練窗的平均與標準差標準化（標準差為 0 時以 1 代替）。
  - **分數與門檻**：`anomaly_score` 為時間窗負載部分（標準化後）的平均平方重建誤差；天氣與日曆只作為判斷條件，不計入分數。結束小時 `>= validation_start` 的時間窗為驗證窗，其餘為訓練窗。驗證窗依結束小時的日曆日由第一個驗證日起交錯分組：第 1、3、5… 個驗證日為校準日，第 2、4、6… 個為保留日；門檻為校準窗重建誤差的 `threshold_quantile` 分位數，`is_anomaly = anomaly_score > threshold`。以整日交錯而非前後對切，使驗證期短於一週時兩組仍分布於相同的平日與週末。沒有訓練窗或校準窗時無法設定門檻，拒絕訓練（`ValueError`）；驗證窗只落在單一日曆日（保留組為空）時只回報 `threshold` 與窗數，健康判定因缺少 `recall`／`false_positive_rate` 而為 `WARNING`。
  - **評估（寫入 MLflow）**：於乾淨保留窗注入三種合成異常並計算門檻下召回率：`recall_sudden_drop`（最後 6 小時負載降 20%）、`recall_pattern_swap`（窗內負載循環位移 12 小時）、`recall_level_shift`（整窗負載升 10%），`recall` 為三者平均；`false_positive_rate` 為乾淨保留窗被判為異常的比例；另記 `threshold`、`calibration_windows`（校準窗數）與 `validation_windows`（保留窗數）。門檻與誤報率取自不同日期的時間窗，誤報率不會因設計而固定接近 `1 - threshold_quantile`，保留日的重建誤差偏高時即可使 `max_false_positive_rate` 判定失敗。已知限制：時間窗以結束小時分組，保留日清晨結束的時間窗與前一個校準日深夜結束的時間窗共用最多 23 小時輸入，最早的驗證窗亦與訓練窗共用輸入，兩組並非完全獨立（取捨見 ADR-0009 Notes）。
  - **預測**：輸出 `datetime`（時間窗結束小時）、`anomaly_score`、`is_anomaly`、`threshold`；`prediction_item` 為 `UnsupervisedReconstructionPrediction`（同名四欄位，不附帶天氣）。
  - **健康判定**：`recall >= min_recall` 且 `false_positive_rate <= max_false_positive_rate` 為 `HEALTHY`，否則 `WARNING`；缺少任一指標時為 `WARNING`。

### 5.3 Runner（`tasks/runner.py`）

Dagster 與 API 只經 runner 使用任務。runner 擁有 I/O 與共用元件（累積門檻、取資料、負載起點過舊、天氣解析與降級、加權天氣）；所有時間相關判斷皆傳入明確 `as_of`（台灣本地 naive 時間）。

| 函式 | 行為 |
| :--- | :--- |
| `check_training_readiness(task, runtime, *, as_of=None)` | 回傳累積摘要；傳入 `as_of` 時只計該時間以前的有效逐時負載，全表任何時間的 legacy 列仍阻擋訓練；未傳入時供排程 skip 與 smoke check 檢查目前累積量 |
| `load_training_data(task, runtime, *, as_of)` | 未達門檻拋 `TaskNotReady`；讀取 `as_of` 以前的目標序列與同期觀測天氣，並以 `validation_fraction` 推導 `validation_start`。觀測天氣為加權天氣：各代表點在同一觀測整點皆有值才合成，任一點缺少的整點沒有加權值，交由任務類型既有的缺值規則處理 |
| `train_task(task, runtime, *, as_of) -> Trained` | `load_training_data` 後交由 `fit_task` |
| `fit_task(task, data) -> Trained` | 以已讀取且通過門檻的 `TrainingData` 交由任務類型訓練 |
| `training_table(data)`／`training_data_from_table(task, table)` | 以目標序列與觀測天氣的時間軸聯集將 `TrainingData` 攤平序列化以便跨 run 保存（包含無負載但有觀測天氣的小時），並無損還原：`load` 只保留有 `load_mw` 的列、`weather` 只保留有任一氣象欄位值的列（完全沒有觀測天氣的小時仍為缺口而非 NaN 列），`validation_start` 由還原後的目標小時以相同切分規則重算 |
| `monitor_task(task, runtime, metrics, *, as_of) -> MonitoringReport` | 未達門檻拋 `TaskNotReady`；以有界查詢讀取有效逐時觀測數與 `as_of` 以前最新目標列，交由任務類型 `assess_health` 依 `[health]` 判定；結果含 `health`、`metrics`、`target_hours`、`latest_target_time`、`latest_target_value` |
| `check_task_ready(task, model, runtime, *, as_of) -> Readiness` | 模型、負載起點、任務類型宣告的 `history_coverage` 與完整 168 小時天氣皆可用時 `ready`，並回報 `mode`；`OBSERVED` 任務只需 lookback 內有測站觀測，`mode` 固定 `normal` |
| `predict_task(task, model, runtime, *, as_of, horizon_hours) -> PredictionOutcome` | 拋出 `MissingLoadHistoryError`、`StaleLoadAnchorError`、`InsufficientLoadHistoryError`、`WeatherUnavailableError`、`ObservedInputsIncompleteError`（皆為 `TaskUnavailableError`，API 對應 HTTP 503）；資料庫錯誤（`SQLAlchemyError`）原樣拋出，不得轉為空資料而偽裝成資料缺口（API 同樣對應 503）；結果含 `mode`、預測、逐時天氣與其來源，三者逐列對應 |

serving 以 `fetch_latest_load(..., at_or_before=as_of)` 取得負載起點，再只讀 `[anchor - lookback_hours, anchor]` 的負載歷史。

`OBSERVED` 任務的 serving 路徑：負載起點過舊檢查照常適用；天氣改讀同一區間 `[anchor - lookback_hours, anchor]` 的測站觀測（加權規則同 `load_training_data`），不讀預報也不降級，`mode` 固定 `normal`。區間內沒有任何觀測時拋 `WeatherUnavailableError`；任務類型未能評分任何請求的結束小時（負載或天氣缺口）時拋 `ObservedInputsIncompleteError`。`PredictionOutcome.weather` 與 `weather_sources` 對齊至每個被評分的結束小時，取該小時以前最新一筆觀測，來源為 `station_observation` 並附 `observed_at`。

### 5.4 模型保存（`tasks/model_store.py`）

- `save_model(root, task_id, model) -> Path`：模型先寫入暫存目錄；Linux 上以 `renameat2(RENAME_EXCHANGE)` 原子交換新舊非空目錄，首次寫入則以單次 rename 安裝；核心或檔案系統不支援交換（`ENOSYS`、`EINVAL`）時，於同一把排他鎖內以 rename 依序移開舊目錄、安裝新目錄，讀取端因等待鎖而不會看到空窗；僅程序於兩次 rename 之間中止時，任務於下次訓練成功前沒有模型，遺留的舊目錄 `.<task_id>.previous` 於下次保存（持排他鎖、安裝前）清除。每任務檔案鎖保護交換與讀取；交換失敗時舊模型仍在正式路徑。`root` 為 `DATA_DIR/models`。
- `load_model(root, task) -> TaskModel | None`：在同一把鎖下讀取 `root/<task_id>`，替換期間只會載入完整的前一版或新模型；目錄不存在時回傳 `None`（任務尚未訓練）；既有 `model.joblib` 不載入。
- 模型檔只使用原生非執行格式：`recursive_regression` 為 `model.txt`（LightGBM Booster 文字格式）與 `metadata.json`（格式版本、任務類型、lag、rolling window、特徵名稱、氣象欄位）；`direct_classification` 同為 `model.txt`（二元分類 Booster 文字格式）與 `metadata.json`（格式版本、任務類型、完整 `[params]`、`max_lead_hours`、特徵名稱、氣象欄位）；`unsupervised_reconstruction` 為 `model.npz`（`coef_{i}`、`intercept_{i}` 各層權重與偏差，`scaler_mean`、`scaler_scale` 標準化參數；以 `allow_pickle=False` 讀取）與 `metadata.json`（格式版本、任務類型、激活函數、層數、`window_hours`、氣象欄位、特徵名稱、`threshold`），推論以 numpy 前向計算，不重建 sklearn 物件。
- `src/` 不得 import `pickle` 或 `joblib`，由測試強制。

---

## 6. 前端語系與格式

> 依 [GitHub #80](https://github.com/shiroki9979/shiro-mlops/issues/80)。程式位於 `frontend/src/i18n/`。

### 6.1 語系與字典

- **支援語系**：`zh-TW`（預設）與 `en`。
- **字典型別**：`zh-TW.ts` 為基準字典，`Messages` 型別由其推導；`en.ts` 以 `Messages` 標註，缺鍵或多出的鍵在 `tsc`（`pnpm build`）時失敗。
- **取值方式**：元件經 `useMessages()` 取得目前語系的字典物件（如 `m.nav.dashboard`），插值以函式值表達（如 `m.dashboard.table.title(hours)`）；元件不直接寫 UI 字面值。
- **用詞**：zh-TW 使用 [GLOSSARY.md](../GLOSSARY.md) 中文正名，en 使用 GLOSSARY 括號內英文；MW、MAPE、CWA、Geocode 等單位與縮寫兩語系皆保留。
- **Data Explorer catalog**：`catalog.ts` 只保存 dataset id、路由、API 路徑、欄位與 filter key；資料集名稱、說明、欄名、filter 標籤與導覽分組標題由字典以 dataset id 與欄位 key 提供。`ExplorerDatasetId` 與 `ExplorerFieldKey` 由字典鍵推導，catalog 引用字典沒有的鍵時 `tsc` 失敗。

### 6.2 翻譯邊界

| 類別 | 範圍 |
| :--- | :--- |
| 經字典翻譯 | UI 字串、錯誤與空狀態訊息、Data Explorer 欄名與布林值、API 狀態 enum（`overall`、`availability`、`freshness`、`completeness`、audit `status`） |
| 維持原值 | 區域名、測站編號、機組名稱、`dataset_id` 等資料內容值；篩選 placeholder 中的合法輸入值；後端 `ApiError` 訊息（`detail`）；CSV 表頭與內容；請求參數與 cursor |

`GET /data/status` 回傳的 `label` 不直接顯示；前端以 dataset `id` 查字典，僅在 id 不在 catalog 時回退為 `label`。

### 6.3 語系選擇與持久化

- **選擇入口**：僅設定頁提供語系選單，選項以各語言自稱顯示（「正體中文」「English」）。
- **持久化**：獨立 `useLocaleStore`（zustand `persist`，key `shiro-locale`），只保存使用者明確選擇；未選擇時不寫入瀏覽器儲存，不保存自動偵測結果。
- **生效語系**：已保存的選擇優先；否則依序檢查 `navigator.languages`，第一個 `zh*` 對應 `zh-TW`、`en*` 對應 `en`，皆不支援時使用 `zh-TW`。
- **文件語系**：`main.tsx` 在初次 render 前呼叫 `syncDocumentLocale()`，設定 `<html lang>` 與 `document.title`，並於切換語系後同步更新。`index.html` 的靜態值只在 JavaScript 載入前生效。

### 6.4 數字與日期時間

- **時區**：所有日期時間格式化經 `src/i18n/format.ts`，明確指定 `timeZone: 'Asia/Taipei'`，不依賴瀏覽器時區；Data Explorer 時間維持整秒格式。
- **數字**：以 `Intl.NumberFormat` 依目前語系分組。
- **Data Explorer 欄位型別**：依欄位 key 的語意對照表辨識時間、日期、量測值、旗標、audit status 與原值；測站編號、Geocode 等識別碼即使形似數字也不格式化。字典沒有的欄位顯示原始 key 與原值。
- **不受語系影響**：請求參數的時間字串（RFC 3339，`+08:00`）、cursor 與 CSV 匯出直接使用 API 原值。

### 6.5 不引入 i18n 套件

目前只有兩種語系、字串量約數百，且不需要 ICU 訊息語法、語系檔動態載入或翻譯平台整合；型別化字典搭配原生 `Intl` 即可由 `tsc` 保證鍵完整，不增加相依套件與 bundle 體積。代價是英文單複數等少數規則以函式值手寫。新增語系、需要翻譯平台流程或複數規則顯著增加時，再評估 i18n 套件。

### 6.6 測試約定

- vitest 全域 `TZ=UTC`，以已知時間點斷言兩語系皆顯示正確的臺北時間。
- 每個測試前將語系重設為 `zh-TW`（jsdom 預設語言為 `en-US`）；整合測試以字典值斷言，不寫死顯示文字。

---

## 7. 研究空間（`lab/`）介面與報告契約

> 依 [ADR-0011](adr/0011-co-locate-lab-workspace-with-unidirectional-dependency.md)。程式位於 `lab/`，相依方向固定為 `lab` → `shiro_mlops`；操作步驟見 [如何執行一次 lab 研究](how-to/run-lab-study.md)。

### 7.1 快照（`lab/snapshot.py`）

| 介面 | 行為 |
| :--- | :--- |
| `write_snapshot(task, runtime, as_of, *, snapshots_dir) -> Path` | 以 `load_training_data` + `training_table` 凍結訓練表；目標檔已存在時拋 `FileExistsError` 且不改動原檔；`TaskNotReady` 原樣拋出 |
| `read_snapshot(task, as_of, *, snapshots_dir) -> TrainingData` | 讀回 parquet 後以 `training_data_from_table` 還原 |
| `snapshot_path(task, as_of, *, snapshots_dir) -> Path` | 回傳 `<snapshots_dir>/<task_id>/<as_of>.parquet`；`as_of` 一律換算為 Asia/Taipei 無時區時間 |

`snapshots_dir` 預設 `data/lab/snapshots`（不進版控）。CLI：`uv run --package lab python -m lab.snapshot <task_id> --as-of <ISO>`。

### 7.2 滾動起點回測（`lab/backtest.py`）

`rolling_origin_backtest(task, data, origins, horizon_hours, *, min_history_hours=None) -> BacktestReport` 為純函式，不做 I/O。

- **起點語意**：起點為最後一筆已知實際負載的整點，預報目標為 `origin + 1h .. origin + horizon_hours`（`target_hours(origin, horizon_hours)`）。
- **訓練**：負載與氣象皆截斷為 `datetime <= origin`，`validation_start = origin + 1h`（驗證集為空）。
- **預報**：`PredictionData.anchor = origin`，`load_history` 含起點當小時；`weather` 為目標時段的完整逐時軸，以正式的觀測氣象對齊規則（2 小時內向後對齊）填入。
- **起點有效性**：每個起點須同時滿足下列條件，任一不合格拋 `ValueError` 並指出起點與條件：
  1. `datetime <= origin` 的有效負載小時數達 `min_history_hours`（預設取任務設定 `policies.min_training_hours`）。
  2. `(origin - lookback_hours, origin]` 的逐時負載完整（含起點當小時）。
  3. 目標時段的實際負載與對齊後觀測氣象皆有值。

`BacktestReport` 欄位：

| 欄位 | 說明 |
| :--- | :--- |
| `overall_mape` | 所有起點、所有提前時數合併的 MAPE（`evaluate_forecast`） |
| `mape_by_horizon` | 提前時數 `1..horizon_hours` 各自的 MAPE |
| `predictions` | 每個起點的預報值序列（依提前時數排序） |
| `origins`、`horizon_hours` | 正規化後的起點清單與視界 |
| `min_history_hours`、`min_history_overridden` | 實際使用的最低累積與是否由呼叫端覆寫 |
| `params` | 所用任務參數 |

`candidate.beats(baseline)`：起點清單與視界相同時，`overall_mape` 嚴格較低即為贏；起點或視界不同時拋 `ValueError`。回測使用觀測氣象，結果為「氣象已知」條件下的條件式數字，不代表正式 serving 誤差，也不是其上界或下界。

### 7.3 搜尋起點與評估起點

- 超參數搜尋的 objective 只在搜尋起點上計算整體 MAPE；是否採用只比較基線與最佳候選在評估起點上的 `BacktestReport`。
- `verify_non_overlapping_target_windows(search_origins, eval_origins, horizon_hours)`：評估起點須全部晚於搜尋起點，且兩組的目標時段不得有任何共同小時；違反時拋 `ValueError`。
- 評估起點不足以代表負載型態時（門檻由研究主題定義並寫入報告），只交付探索報告，不修改任務設定 TOML。

### 7.4 MLflow 隔離

lab 的 run 記錄於 experiment `lab/<topic>`；不得呼叫 model registry 的任何寫入操作。MLflow 不可用時記錄警告並繼續。

### 7.5 研究報告（`lab/<YYYY-MM-DD>-<topic>/README.md`）

固定段落依序為：問題、快照、回測設定、基線、候選、結論、是否採用。回測設定段須含觀測氣象條件式聲明（§7.2）。採用時在任務設定 TOML 參數旁註解連回報告。

重現紀錄欄位（不依賴 MLflow 可用）：

| 欄位 | 內容 |
| :--- | :--- |
| Git revision | 產生報告數字的 commit SHA |
| 快照 | `task_id`、`as_of`、code span 路徑、檔案 SHA-256 |
| 基線參數 | 任務設定 TOML 路徑與完整 `[params]` |
| 候選參數 | 最佳候選完整參數 |
| 起點 | 搜尋起點與評估起點完整清單 |
| 視界 | `horizon_hours` |
| 最低累積 | `min_history_hours`、是否覆寫與理由 |
| 搜尋設定 | 搜尋空間、seed、trial 數 |
| 分組誤差 | 搜尋與評估起點的 `1..horizon_hours` 各分組 MAPE |

不進版控的路徑（快照、`*.ipynb`）以 code span 引用，不用 Markdown 連結。
