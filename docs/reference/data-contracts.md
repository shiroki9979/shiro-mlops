# 資料模型與契約 (Data Contracts)

- 建立日期：2026-11-20
- 最後更新：2026-11-22
- 專案版本：`0.4.0`

> 由 `docs/SPEC.md` 第 1 節拆出。

---

## 1. 台電用電負載實體 (Taipower Load Schema)

- **資料來源**：由 `raw_taipower_regional_supply_demand_snapshot` 推算之全台逐時實際負載（[ADR-0008](../adr/0008-derive-hourly-actual-load-from-regional-snapshots.md)）；不使用每日尖峰負載、全台供需快照或機組淨發電量。
- **推算契約**：
  - **有效樣本**：以區域快照 `source_time` 識別；同一 `source_time` 重複擷取只計一次；北、中、南、東四區皆存在時才有效，四區 `load_wan_kw` 加總乘以 10 轉為 MW。
  - **逐時聚合**：`datetime` 為小時起點（台灣本地時間），`load_mw` 為 `[datetime, datetime + 1h)` 內有效樣本平均；有效樣本數低於 `HOURLY_LOAD_MIN_SAMPLES`（預設 `4`，每小時最多 6）時該小時缺值，不內插；未結束的小時不產出。
  - **可取得範圍**：只自開始累積區域快照時往後取得，不回補歷史。
- **預測對象**：全台逐時實際負載的預測對象識別碼固定為 `nationwide`（[ADR-0009](../adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md)）。預測對象只識別負載序列本身，與天氣取自哪個氣象代表點無關。
- **欄位契約**：

| 欄位名稱 | 型態 | 單位/範例 | 說明 |
| :--- | :--- | :--- | :--- |
| `datetime` | `datetime64[ns]` | `2026-08-20 14:00:00` | 時間戳記（逐時） |
| `subject` | `str` | `nationwide` | 預測對象識別碼 |
| `load_mw` | `float64` | `39800.0` | 當前系統總用電負載（百萬瓦） |

## 2. 中央氣象署資料實體 (CWA Weather Schemas)

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

### 2.1 氣象署逐時測站觀測

- **資料來源**：中央氣象署 OpenData API `O-A0001-001`。
- **身分契約**：以來源 `StationId` 作為穩定測站識別；測站名稱僅作顯示與跨來源映射，不參與身分判定。
- **時間契約**：以來源 `ObsTime/DateTime` 作為觀測發生時間。
- **Typed 氣象因子**：氣溫、相對濕度、測站氣壓、降水量、風速與風向；無法正規化的其他來源欄位仍保留於完整原始回應。

### 2.2 氣象署鄉鎮預報版本

- **資料來源**：中央氣象署 OpenData 原始檔 API `F-D0047-089`（未來三日）與 `F-D0047-091`（未來一週）。預報 ingestion 必須使用保留 `IssueTime`／`Update` 的原始 XML 檔，不得使用省略版本時間的 flattened REST 回應。
- **身分契約**：以來源 `Geocode` 作為穩定行政區識別；鄉鎮名稱僅作顯示與跨來源映射。
- **版本契約**：同一行政區與預報有效時間的不同發布版本必須並存，不得以新版覆寫舊版；資料身分至少包含資料集編號、發布時間、有效時間與 `Geocode`。
- **時間契約**：發布時間與預報有效時間分開保存，以支援 point-in-time correct 的預測重現與回測。
- **版本時間驗證**：來源未提供或無法解析 `IssueTime`／`Update` 時，ingestion 必須失敗；不得以擷取時間冒充來源版本時間。
- **Typed 氣象因子**：溫度、露點溫度、體感溫度、相對濕度、降雨機率、風速與風向；天氣現象、舒適度描述及其他來源欄位仍保留於完整原始回應。

## 3. 地端時序資料庫模型 (TimescaleDB Hypertables)

- **資料庫**：`shiro_timeseries` (TimescaleDB / PostgreSQL 15+)
- **時間契約**：擷取與特徵工程邊界的無時區時間均表示台灣本地時間（`Asia/Taipei`）；帶時區的來源時間保留其原始瞬間。寫入 `TIMESTAMPTZ` 前，repository 一律轉為 UTC；範圍查詢條件同樣轉為 UTC。讀回資料在交給特徵工程前轉回無時區的台灣本地時間。
- **Payload 契約**：`raw_payload` 與 `missing_*` 等 `JSONB` 欄位一律以同一份序列化寫入合法 JSON 文字：物件與陣列保存為 JSON 物件與陣列（保留非 ASCII 字元），字串 payload（如氣象署預報原始 XML）保存為 JSON 字串字面值，不得原樣寫入。讀回時物件與陣列 payload 以對應的反序列化還原；PostgreSQL 驅動回傳的 `JSONB` 已是解析後的值，字串 payload 不得再當作 JSON 文字解析，目前也沒有讀取字串 payload 的讀取端。
- **主表結構**：
  1. `raw_taipower_load`:
     - `time` (TIMESTAMPTZ, NOT NULL)
     - `subject` (VARCHAR(64), NOT NULL)：預測對象識別碼；全台逐時實際負載為 `nationwide`。
     - `load_mw` (DOUBLE PRECISION, NOT NULL)
     - `source` (VARCHAR(32), NOT NULL)：推算來源；目前唯一值為 `regional_snapshot_sum`。
     - `created_at` (TIMESTAMPTZ DEFAULT NOW())
     - **預測對象遷移**：ADR-0009 之前的資料庫以 `location = 'Taipei'` 保存全台負載。服務啟動時的 schema 升級在單一交易內將 `location` 改名為 `subject`，並把 `Taipei` 列改為 `nationwide`；已遷移的資料庫重跑時不改動任何列。新建資料庫直接採 `subject`。升級順序見[遷移全台負載預測對象](../how-to/migrate-load-subject-to-nationwide.md)。
     - 啟用推算前須確認並清除 d015046 時期留下的資料列，不得與推算序列混用。既有資料庫升級時只補上可為 `NULL` 的 `source`，不改寫或刪除任何列；`source IS NULL` 即 d015046 時期資料列。清除與補上 `NOT NULL` 由操作人員依[移除 d015046 時期舊負載資料列](../how-to/remove-legacy-d015046-load-rows.md)執行後，才開啟 `hourly_actual_load_schedule`。
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
     - 保存北、中、南、東四區的區域發電量與區域用電負載成對快照，與全台 `raw_taipower_supply_demand_snapshot` 及 `raw_taipower_load` 分離，且不得直接成為訓練特徵的輸入；唯一例外為 §1 全台逐時實際負載推算。
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
  9. `issued_forecast`（已發布預報 header，[ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md)）：
     - 每個發布時刻一列，由 `issued_forecast_job`（[Dagster 排程](dagster-schedules.md)）寫入；隨需 `/predict` 不寫入。一般資料表，非 hypertable。
     - `issued_at` (TIMESTAMPTZ, NOT NULL)：發布時刻，即排程 tick 時刻與預報的 `as_of`，不取整點（例如 `10:15`）。
     - `load_anchor` (TIMESTAMPTZ, NOT NULL)：負載起點，即遞迴預報起算的最新實際負載小時。
     - `status` (VARCHAR(16), NOT NULL)：運行狀態 `normal`／`degraded`，即預報當時的天氣解析模式（§3.3）。
     - `model_sha256` (VARCHAR(64), NOT NULL)：模型版本識別，發布時實際載入的模型目錄雜湊（完整 64 字元小寫十六進位，定義見 [ML 任務設定 §4](ml-tasks.md#4-模型保存tasksmodel_storepy)），不依賴 MLflow。
     - `mlflow_model_version` (VARCHAR(64))：MLflow 版本附註，可為 `NULL`；只作參考，模型版本以 `model_sha256` 為準。發布時從 Dagster instance 讀 `dynamic_horizon_forecast__model` 最新一次 materialization 的 metadata（[Dagster 排程](dagster-schedules.md)）：只有其 `model_sha256` 等於本次實際載入模型的雜湊時，才填入其 `mlflow_model_version`；雜湊不符（例如訓練恰在載入模型後完成）、缺少 metadata 或 MLflow 版本為空時為 `NULL`（寧缺勿錯）。不另呼叫 MLflow，附註的有無不影響是否發布。
     - **Constraint**: `PRIMARY KEY (issued_at)`；只新增、沒有更新路徑。同一發布時刻已存在時以 `ON CONFLICT (issued_at) DO NOTHING` 略過，header 與步數皆不改動。
     - 永久保留，不設定資料保留政策。
  10. `issued_forecast_step`（已發布預報步數）：
      - 與同一發布時刻的 header 於同一 transaction 寫入；header 已存在時不寫入任何步數。
      - `issued_at` (TIMESTAMPTZ, NOT NULL)：所屬 header 的發布時刻。
      - `target_hour` (TIMESTAMPTZ, NOT NULL)：目標小時，負載起點後第 1 至 168 小時。
      - `predicted_load_mw` (DOUBLE PRECISION, NOT NULL)：預測負載（MW）。
      - **Constraint**: `PRIMARY KEY (issued_at, target_hour)`。
      - **Hypertable**: `create_hypertable('issued_forecast_step', 'issued_at')`，以發布時刻分區。
      - 模型產出的步數原樣全存：不過濾目標小時不晚於發布時刻的步，也不保存天氣值與天氣來源。
      - 永久保留，不設定資料保留政策。

### 3.1 CWA 既有資料遷移

- 既有 `raw_cwa_weather` 不具可信的 `StationId` provenance；建立 canonical CWA tables 後，全部既有列保留於唯讀 `legacy_cwa_weather`，不得遷入 canonical table，也不得再成為正式消費端的新資料來源。
- migration 必須保留既有資料，且可安全重跑。
- canonical typed data、batch／release 原始回應及 `legacy_cwa_weather` 均永久保留，不設定資料保留政策。

### 3.2 CWA 特殊值與批次完整度

- `X`、`-` 與 `-99` 正規化為 `NULL`；降水量 `T` 與 `-98` 正規化為 `0.0 mm`；風向 `990` 正規化為 `NULL`。來源原值仍可由 batch／release 的 `raw_payload` 追溯。
- allowlist 中任一測站或行政區缺少時，以單一 transaction 寫入所有有效 child rows，將 header 標為 `incomplete`，再使 asset 失敗以觸發有限重試；重試不得產生重複觀測或預報版本。

### 3.3 CWA 預報版本選取與逐時投影

- 只能選取 `issued_at <= prediction_time` 的預報版本，禁止使用預測當時尚未發布的資料。
- 每個氣象代表點、每個有效小時與 typed 欄位依序取值：發布未超過七小時的 `F-D0047-089` → 發布未超過七小時的 `F-D0047-091` → 測站前日同小時觀測 → 同月份同小時歷史平均。七小時以實際提供該數值的預報版本 `issued_at` 判定，而非兩個 dataset 中較新的版本；門檻只定義於 `shiro_mlops.data.weather_resolution.FORECAST_STALE_AFTER`。
- `F-D0047-089` 的連續數值點資料在相鄰時間點間線性插值；`F-D0047-091` 的區間平均值展開為有效區間內每小時固定值；風向與文字／代碼不得線性插值。
- 可消費 `incomplete` header 中已存在的指定行政區資料；指定行政區缺少時，退回上一個含有該行政區資料的版本，不要求該版本 `complete`。
- 預報與觀測皆取自同一氣象代表點：預報讀其 `geocode`，替代資料讀其 `station_id`。
- 改用 `F-D0047-091` 仍屬正常預報；只有以觀測填補的數值才使整次預報成為 `mode: degraded`，其餘仍有效的預報數值照常採用。月份／小時常模至少須涵蓋七個不同日期，否則視為無可用替代資料；任一數值無替代資料即無法產出。
- Data Explorer 狀態的 `latest_release_stale` 只表示該資料集最新發布是否超過同一七小時門檻，屬資料集層級的粗略訊號，不等同單次請求的降級判定。
- 多氣象代表點（[ADR-0012](../adr/0012-combine-weather-reference-points-into-weighted-weather.md)）：每個代表點各自依上列規則選版、投影與降級，再依任務設定權重逐小時合成加權天氣。任一點降級，整次即為 `mode: degraded`；任一點連替代資料都無法涵蓋某小時，整次即無法產出（HTTP 503），不剔除該點、不重新正規化。

## 4. Feast 特徵庫視圖 (Feature View Schema)

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
- **匯出來源**：`cwa_weather_features` 為預測對象的加權天氣（[ML 任務設定 §3](ml-tasks.md#3-runnertasksrunnerpy) runner 讀取觀測時合成）。Feast 凍結為動態視界預報任務專屬匯出，由 `dynamic_horizon_forecast__features` 的訓練表（[Dagster 排程](dagster-schedules.md)，經 [ML 任務設定 §3](ml-tasks.md#3-runnertasksrunnerpy) `training_data_from_table` 還原為目標序列與觀測天氣）自行計算上列欄位，不共用任何任務的特徵配方；Feast 無正式讀取者。
- **時間正確性**：訓練資料由 runner 以明確 `as_of` 讀取 `as_of` 以前的目標序列，時間窗由已累積的目標列推導；serving 只讀負載起點往前 `lookback_hours`（[ML 任務設定 §3](ml-tasks.md#3-runnertasksrunnerpy)）的歷史，禁止無界歷史掃描。lag 依時間戳取前 `L` 小時的負載，rolling 只統計前 `W` 小時內已有的觀測；缺漏小時不得由相鄰資料列冒充。lag / rolling 缺值不得以未來用電負載（`bfill`）填補，warm-up 列使用非洩漏哨兵值 `0.0`。
- **訓練氣象缺口**：氣溫與相對濕度只能由較早觀測 forward-fill 最多兩小時；補值後仍缺少任一必要氣象欄位的 load row 必須移除。禁止 `bfill` 與固定氣象常數。

## 5. Dagster Artifact 序列化與信任邊界

- 本機 `DATA_DIR` 下的 artifact 視為讀取時的非信任位元組；檔案系統寫入權限不等同於可安全執行其內容。
- DataFrame artifact 使用 Parquet；非 DataFrame artifact 僅允許 JSON-compatible 值，並以 `SHIRO-JSON-V1` envelope 標記後保存。
- loader 僅接受 Parquet magic 或 `SHIRO-JSON-V1` envelope；未識別格式（包含既有未標記 pickle）必須失敗，禁止執行 pickle 反序列化。
- 既有 pickle artifact 不提供相容性載入；需重新 materialize Dagster asset 產生新的 JSON artifact。此為明確的遷移策略。

### 5.1 預報實績 `forecast_track_record`

資產 `forecast_track_record`（[Dagster 排程](dagster-schedules.md)第 7 項，[ADR-0013 §2.3](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md#23-預報檢視的最低呈現內容)）回傳 frozen dataclass `ForecastTrackRecord`（`data/forecast_track_record.py`），由 `io_manager` 以 `SHIRO-JSON-V1` 保存為 JSON 物件，下游的 `forecast_view_export` 以 input 讀取並投影為公開的預報實績 JSON（第 6 節）。累積天數未滿 7 時：

```json
{"cutoff": "2026-11-20T10:00:00", "accumulated_days": 3, "metrics": null}
```

累積天數滿 7 時（曲線與時序節錄）：

```json
{
  "cutoff": "2026-11-20T10:00:00",
  "accumulated_days": 9,
  "metrics": {
    "lead_time_curve": [
      {"lead_time_hours": 1, "mape": 2.41, "mae": 612.5},
      {"lead_time_hours": 168, "mape": null, "mae": null}
    ],
    "lead_24": {"lead_time_hours": 24, "mape": 4.87, "mae": 1240.3},
    "lead_24_series": [
      {"target_hour": "2026-11-13T09:00:00", "actual_load_mw": 25012.0, "predicted_load_mw": 25830.4}
    ]
  }
}
```

- `cutoff`（字串）：統計截至時刻，台灣本地時間的整點，ISO 8601 不帶時區。計入的目標小時為 `[cutoff − 720h, cutoff)`。
- `accumulated_days`（整數，0–31）：累積天數，即窗內有配對（任一提前時數）的目標小時取台灣日期去重後的天數。尚無已發布預報時為 `0`。一律輸出。
- `metrics`（物件或 `null`）：`accumulated_days` 未滿 7 時為 `null`，曲線、提前 24 指標與時序都不產出，由資料源頭決定，不交給前端隱藏。滿 7 時為下列三個欄位：
  - `lead_time_curve`（陣列）：提前時數 1–168 固定 168 格，依提前時數排序。每格 `mape`（%）= mean(|預測 − 實際| / 實際) × 100、`mae`（MW）= mean(|預測 − 實際|)；窗內同一提前時數的所有配對混在一起算，不先按日或按發布時刻平均。沒有配對的格子 `mape` 與 `mae` 皆為 `null`，不設每格最少配對數。提前 168 在正常營運下恆為 `null`：負載起點至少落後發布時刻一小時，提前時數最大只到 167。
  - `lead_24`（物件）：提前 24 的 MAPE 與 MAE，即 `lead_time_curve` 第 24 格，欄位相同；窗內沒有提前 24 配對時 `mape` 與 `mae` 為 `null`。
  - `lead_24_series`（陣列）：窗內同時有提前 24 已發布預報與有效逐時觀測的目標小時，每點 `target_hour`（字串，格式同 `cutoff`）、`actual_load_mw`、`predicted_load_mw`（MW），依目標小時排序，每個目標小時恰好一點。缺的小時直接省略，不補 `null`。同一目標小時有兩份發布都落在提前 24 時（只在發布間隔不足一小時時發生）取發布時刻較晚者；曲線仍計入兩者。
- 不含運行狀態、天氣來源、模型版本與資料缺口；窗內配對數與提前 24 配對數只記在 materialization metadata，不在輸出內。

## 6. 預報檢視公開 JSON（`/published/`）

資產 `forecast_view_export`（[Dagster 排程](dagster-schedules.md)第 8 項，[ADR-0015 §2.4](../adr/0015-publish-forecast-view-as-static-precomputed-output.md#24-公開資料契約)）每次執行都覆寫下列兩個固定檔名，不保留歷史。預報檢視只以相對路徑 `/published/<檔名>` 讀取；地端由 Nginx 提供地端目錄，雲端由 CloudFront 提供 S3（[預報檢視託管](forecast-view-hosting.md)）。

| 檔名 | 內容 | 地端路徑 | S3 key |
| :--- | :--- | :--- | :--- |
| `latest_issued_forecast.json` | 最新已發布預報（§6.1） | `DATA_DIR/published/latest_issued_forecast.json` | `published/latest_issued_forecast.json` |
| `forecast_track_record.json` | 預報實績（§6.2） | `DATA_DIR/published/forecast_track_record.json` | `published/forecast_track_record.json` |

- **欄位逐一列舉**：兩份 JSON 由 `data/forecast_view.py` 逐欄投影產生，上游新增的欄位不會自動公開。運行狀態、負載起點、天氣值、天氣來源、模型版本與資料缺口都不輸出。
- **時刻格式**：所有時刻為台灣本地時間、ISO 8601 帶 `+08:00` offset（例如 `2026-11-20T10:15:00+08:00`），觀眾瀏覽器不論位於哪個時區都能換算距當下的時間。與 §5.1 的 Dagster artifact（不帶時區）不同。
- **編碼**：UTF-8 JSON，不含 `NaN` 或無限大；出現時匯出失敗，不寫出無效 JSON。HTTP `Content-Type` 為 `application/json`；`Cache-Control` 由 Nginx 與 CloudFront 決定，上傳端不設定物件 metadata。
- **空狀態只由內容決定**：還沒有已發布預報、或累積天數未滿 7 時，兩份 JSON 仍照常輸出（見各小節），前端不以 HTTP 狀態碼推斷空狀態。
- **fixtures**：`tests/fixtures/published/` 是兩份 JSON 的範例，由單元測試核對與匯出結果一致，也供 Nginx smoke check 掛載。前端的 Docker 建置只含 `frontend/`，因此預報檢視的 MSW 另存一份 `latest_issued_forecast.json` 副本於應用內，由前端單元測試核對與此 fixture 相同。

### 6.1 最新已發布預報 `latest_issued_forecast.json`

發布時刻最晚的一份已發布預報（[§3](#3-地端時序資料庫模型-timescaledb-hypertables) 的 `issued_forecast`），不論距今多久；過舊提示由前端依 `issued_at` 判斷。

```json
{
  "issued_at": "2026-11-20T10:15:00+08:00",
  "steps": [
    {"target_hour": "2026-11-20T11:00:00+08:00", "predicted_load_mw": 31250.5},
    {"target_hour": "2026-11-20T12:00:00+08:00", "predicted_load_mw": 31980.0}
  ]
}
```

- `issued_at`（字串或 `null`）：預報時刻，即發布時刻。
- `steps`（陣列）：只含目標小時晚於 `issued_at` 的步，依目標小時排序；每步 `target_hour`（字串）與 `predicted_load_mw`（MW）。負載起點落後 $k$ 小時時，目標小時不晚於發布時刻的前 $k$ 步不輸出，因此步數為 $168 - k$。
- 還沒有任何已發布預報時為 `{"issued_at": null, "steps": []}`。

### 6.2 預報實績 `forecast_track_record.json`

最近一次 `forecast_track_record` materialization（§5.1）的公開欄位，即 [ADR-0013 §2.3](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md#23-預報檢視的最低呈現內容) 的公開欄位加上統計截至時刻。結構與 §5.1 相同，差別只在時刻帶 `+08:00`：

```json
{
  "cutoff": "2026-11-20T10:00:00+08:00",
  "accumulated_days": 9,
  "metrics": {
    "lead_time_curve": [
      {"lead_time_hours": 1, "mape": 2.41, "mae": 612.5},
      {"lead_time_hours": 168, "mape": null, "mae": null}
    ],
    "lead_24": {"lead_time_hours": 24, "mape": 4.87, "mae": 1240.3},
    "lead_24_series": [
      {"target_hour": "2026-11-13T09:00:00+08:00", "actual_load_mw": 25012.0, "predicted_load_mw": 25830.4}
    ]
  }
}
```

- `cutoff`：統計截至時刻；`accumulated_days`：累積天數；`metrics`：未滿 7 天時為 `null`。各欄位的計算規則見 §5.1，數值原樣輸出、不另行四捨五入。
- 還沒有已發布預報時為 `{"cutoff": "<統計截至時刻>", "accumulated_days": 0, "metrics": null}`。
- `forecast_track_record` 從未 materialize 過時（全新環境）同為此空狀態，`cutoff` 取匯出執行當下的整點，即該時刻彙整在首次發布前會得到的結果。
- 窗內配對數與提前 24 配對數不輸出（只在 §5.1 的 materialization metadata）。
