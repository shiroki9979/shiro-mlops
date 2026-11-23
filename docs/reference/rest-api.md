# API 介面規格 (REST Interface)

- 建立日期：2026-11-20
- 最後更新：2026-11-23
- 專案版本：`0.4.0`

> 由 `docs/SPEC.md` 第 2 節拆出。

---

## 1. 健康狀態檢查

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
        "model_loaded": true,
        "model_sha256": "3f6c…（64 字元）",
        "reason": null
      },
      "high_load_alert": {
        "task_type": "direct_classification",
        "model_loaded": false,
        "model_sha256": null,
        "reason": "Model is not loaded or trained yet."
      },
      "load_pattern_anomaly": {
        "task_type": "unsupervised_reconstruction",
        "model_loaded": true,
        "model_sha256": "9a01…（64 字元）",
        "reason": null
      }
    },
    "data_explorer_enabled": true
  }
  ```

- 此端點只代表 process liveness，存活時固定回傳 HTTP 200；不得因模型或資料尚未就緒而改回 503。
- `model_loaded` 為相容欄位，僅代表 `/predict` 所服務的動態視界預報任務模型；`tasks` 以 `task_id` 為鍵，逐一揭露每個已部署任務的任務類型與模型載入狀態。
- `tasks.<task_id>.model_sha256` 為 API 啟動時實際載入的模型目錄雜湊（完整 64 字元小寫十六進位，定義見 [ML 任務設定 §4](ml-tasks.md#4-模型保存tasksmodel_storepy)），與已發布預報的 `model_sha256` 同一定義；沒有模型時為 `null`。`reason` 在沒有模型時說明原因，與該任務 `/ready` 的 `reason` 相同（未訓練或載入失敗，見 [§2](#2-就緒狀態檢查)）；模型已載入時為 `null`。
- `data_explorer_enabled` 表示當前 process 是否開放 Data Explorer 讀取面（`ENVIRONMENT=local` 或 `DATA_EXPLORER_ENABLED=true`）。

## 2. 就緒狀態檢查

- **路徑**：`GET /tasks/{task_id}/ready`；`GET /ready` 為動態視界預報任務 `dynamic_horizon_forecast` 的別名，回應與 `GET /tasks/dynamic_horizon_forecast/ready` 相同。
- **未知任務**：`task_id` 不在已部署任務設定中時回傳 HTTP 404。
- **回應 Body**：`status`（`ready` 或 `not_ready`）、`mode`、`model_loaded`（該任務）、`reason`。`mode` 在 OpenAPI 為 `ForecastMode` enum（`normal`、`degraded`）或 `null`；未就緒時為 `null`。
- **就緒狀態與回應的對應**：一個已部署任務的就緒狀態是封閉的六態，由 `ServedTasks.readiness` 原樣交給 HTTP adapter，只在 adapter 投影成下表的欄位與狀態碼。

  | 就緒狀態 | HTTP | `status` | `mode` | `model_loaded` | `reason` |
  | :--- | :--- | :--- | :--- | :--- | :--- |
  | 未訓練 | 503 | `not_ready` | `null` | `false` | `Model is not loaded or trained yet.` |
  | 載入失敗 | 503 | `not_ready` | `null` | `false` | `Model failed to load: <例外類型>: <訊息>` |
  | 輸入不可用 | 503 | `not_ready` | `null` | `true` | runner 拒絕的訊息（`TaskUnavailableError`，例如負載起點過舊）；持久層不可用（SQLAlchemy 錯誤）時為 `Persistence unavailable: <訊息>` |
  | 檢查失敗 | 503 | `not_ready` | `null` | `true` | 非預期錯誤的訊息 |
  | 就緒（正常） | 200 | `ready` | `normal` | `true` | `null` |
  | 就緒（降級） | 200 | `ready` | `degraded` | `true` | `null` |

- **例外分類**：就緒檢查與預測（[§4](#4-通用任務推論) 的錯誤對應）共用同一條規則。runner 的拒絕與持久層不可用歸為輸入不可用，不記 traceback；持久層不可用時 `reason` 與該任務 `/predict` 的 `detail` 同為 `Persistence unavailable: <訊息>`。其他非預期錯誤記下 traceback 後歸為失敗。兩者只差在 HTTP 對映：就緒檢查的失敗回傳 HTTP 503 `not_ready`（traceback 寫入日誌），不回 500；預測的失敗回傳 HTTP 500。
- **語意**：模型已載入、負載起點未過舊，且預報天氣任務的正常或降級氣象來源可涵蓋完整 168 小時時回傳 HTTP 200；body 必須揭露 `mode: normal` 或 `mode: degraded`。模型或必要資料不足、或負載起點過舊時回傳 HTTP 503，並列出未就緒原因。
- **觀測天氣任務**（任務類型 `requirements().weather` 為 `OBSERVED`，例如 `load_pattern_anomaly`）：不讀預報、不降級；模型已載入、負載起點未過舊，且錨點結束小時有完整的負載與測站觀測評分窗時回傳 HTTP 200 與 `mode: normal`，否則回傳 HTTP 503。
- **負載起點過舊**：最新推算列（`source = 'regional_snapshot_sum'`）的 `raw_taipower_load.time` 早於請求時間超過任務設定 `[policies].stale_anchor_max_lag_hours`（預設 `3`）小時；此狀態不降級，`/ready` 與 `/predict` 皆回傳 HTTP 503。
- **模型**：API 啟動時依任務設定逐一載入 `DATA_DIR/models/<task_id>/`（[ML 任務設定 §4](ml-tasks.md#4-模型保存tasksmodel_storepy)）；單一任務的模型目錄不存在或無法載入時，只有該任務維持 `not_ready`，其他任務照常服務。未訓練（模型目錄不存在）時 `reason` 為 `Model is not loaded or trained yet.`；載入失敗時 `reason` 為 `Model failed to load: <例外類型>: <訊息>`，完整 traceback 寫入日誌。兩者皆回傳 HTTP 503，該任務的 `/predict` 以同一字串作為 `detail`。既有 `DATA_DIR/model.joblib` 不載入，首次以新格式重新訓練前 `/ready` 維持 `not_ready`。任務設定無效時 API 啟動失敗。
- 空資料庫首次啟動時 API process 可存活，但不得由 API lifespan 直接呼叫 CWA 或以測試資料建立正式模型。
- **資料庫**：API 啟動時確保一次 schema（`init_db`），之後所有 request 共用同一個 repository 與連線池，不再逐 request 執行 DDL。啟動時資料庫無法連線只記錄錯誤，API 之後不會自行補建 schema；資料庫恢復連線後即可讀取既有資料表。資料庫記錄了本程式不認得的 schema 遷移（由較新版本的程式遷移過）時 API 啟動失敗，不支援降版（[資料模型與契約 §3.4](data-contracts.md#34-schema-遷移紀錄-schema_migration)）。

## 3. 隨需動態視界負載預報

- **路徑**：`POST /predict`（動態視界預報任務 `dynamic_horizon_forecast` 的別名，與 §4 共用 runner `predict_task` 與錯誤對應；預測 item 即該任務的 item（`PredictionItem`：`datetime`、`predicted_load_mw`、`temperature`、`relative_humidity`、`weather_sources`），同一請求的 `predictions` 與 `POST /tasks/dynamic_horizon_forecast/predict` 相同）
- **預測對象**：固定為 `nationwide`，並於回應 `subject` 揭露；模型只預測全台負載，不宣稱支援區域負載模型。
- **相容性欄位**：請求 `location` 為選填，於 OpenAPI 標示 `deprecated`；任何值皆被忽略，不影響預測對象，也不再回傳 HTTP 400。回應不再包含 `location`。
- **資料來源**：只讀 canonical TimescaleDB tables。負載歷史與遞迴起點只取 `source = 'regional_snapshot_sum'` 的列，`source IS NULL` 的 d015046 舊列一律忽略。氣象以請求時間為 `as_of`：只採用請求當下已發布且已更新的預報版本；某數值沒有發布未超過七小時的預報版本可提供時（以提供該數值的版本判定，[資料契約 §3.3](data-contracts.md#33-cwa-預報版本選取與逐時投影)），該數值依序退回氣象代表點測站的前日同小時觀測、同月份同小時歷史平均，並回傳 `mode: "degraded"`；替代資料皆不存在，或負載起點過舊（§2）時回傳 HTTP 503。
- **狀態欄位**：`status` 表示請求成功（固定為 `success`）；`mode` 表示預報運行狀態（`normal` 或 `degraded`），兩者不得混用。`mode` 為 required，OpenAPI 以 `ForecastMode` enum 描述，無預設值。
- **不寫入已發布預報**：隨需預報只讀不寫；已發布預報只由每小時的 `issued_forecast_schedule` 產生（[Dagster 排程](dagster-schedules.md)、ADR-0013）。
- **來源追溯**：每個預測點的 `weather_sources` 依「氣象欄位 → 氣象代表點別名 → 來源」逐一揭露每個代表點的來源，以及可用的預報發布／更新時間；只有一個代表點時也採同一形狀。同一時點允許不同欄位或不同代表點來自不同產品或降級來源。每個來源的 `source` 屬於封閉集合，其餘欄位由 `source` 決定：`three_day`、`weekly` 帶預報版本 `dataset_id`、`issued_at`、`source_updated_at`；降級來源 `previous_day_observation`、`climatology` 只有 `source`；觀測天氣任務的 `station_observation` 帶 `observed_at`。來源中的時間為台灣本地時間，ISO 8601 不帶時區。
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
              "dataset_id": "F-D0047-089",
              "issued_at": "2026-08-21T23:00:00",
              "source_updated_at": "2026-08-21T23:20:00"
            }
          },
          "relative_humidity": {
            "Taipei": {
              "source": "weekly",
              "dataset_id": "F-D0047-091",
              "issued_at": "2026-08-21T23:00:00",
              "source_updated_at": "2026-08-21T23:25:00"
            }
          }
        }
      }
    ]
  }
  ```

## 4. 通用任務推論

- **路徑**：`POST /tasks/{task_id}/predict`（ADR-0009）
- **請求 Body**：`horizon_hours`（整數 1–168，預設 24）；不接受 `location`。語意依任務的天氣輸入而定：
  - 預報天氣任務（`FORECAST`）：負載起點之後預測的小時數（預測視界）。
  - 觀測天氣任務（`OBSERVED`）：評分最近幾個時間窗結束小時，由負載起點往回算，即結束小時落在 `(anchor - horizon_hours, anchor]`；不預測未來。資料有缺口的時間窗不評分，因此回傳筆數可能少於 `horizon_hours`，但不以常數補值。
- **回應 Body**：共通欄位 `status`（固定為 `success`）、`task_id`、`task_type`、`subject`、`mode`（required 的 `ForecastMode` enum，同 §3），以及 `predictions`；`predictions` 的 item schema 由任務類型的 `prediction_item` 與任務設定的 `weather.fields` 共同決定（[ML 任務設定 §2](ml-tasks.md#2-任務類型介面taskstypes)），OpenAPI 以每個任務的 `<TaskId>TaskPredictionResponse`（item 為 `<TaskId>PredictionItem`，未附帶天氣者直接沿用任務類型的 item）逐一描述，並以 `task_id` 常數區分；回應模型於建構時驗證，端點不再以聯集重驗。
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
        "weather_sources": {
          "temperature": {
            "Taipei": {
              "source": "three_day",
              "dataset_id": "F-D0047-089",
              "issued_at": "2026-08-21T23:00:00",
              "source_updated_at": "2026-08-21T23:20:00"
            }
          }
        }
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
        "weather_sources": {
          "temperature": {
            "Taipei": {
              "source": "three_day",
              "dataset_id": "F-D0047-089",
              "issued_at": "2026-08-21T23:00:00",
              "source_updated_at": "2026-08-21T23:20:00"
            }
          }
        }
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

## 5. Data Explorer series

Data Explorer 圖表使用的有界序列查詢。與 list endpoints 相同，僅在 local environment 或 `DATA_EXPLORER_ENABLED` 時可用（其餘情況回 HTTP 404）；產品語意見 [data-explorer.md](data-explorer.md) §8。

### 5.1 共用參數

每個 series endpoint 的路徑為對應 list 路徑再加 `/series`。

| 參數 | 型別 | 預設 | 說明 |
| --- | --- | --- | --- |
| `start`、`end` | RFC 3339 | `end` = 現在，`start` = `end` − 24 小時 | 與 list 相同的精確閉區間；無 offset 時視為台北時間。窗口最長 92 天，與各 list 的天數上限無關。 |
| `fields` | 可重複的列舉 | 該資料集的預設欄位（§5.4） | `fields=a&fields=b`；重複的欄位只產生一條 series，series 依請求順序排列。 |
| `group_by` | 依資料集的列舉 | 該資料集的預設分組 | 只有允許切換分組的資料集接受（見 §5.4）；其餘資料集帶此參數回 422。 |
| `bucket` | `auto` \| `raw` \| `1h` \| `1d` | `auto` | `auto` 解析為同時符合兩個點數上限的最細粒度（依 `raw`、`1h`、`1d` 順序）。 |
| `agg` | `avg` \| `min` \| `max` | `avg` | bucket 內的時間聚合；`raw` 忽略此參數。 |
| 資料集篩選 | 依資料集 | — | 見 §5.4。 |

- 參數一律以列舉驗證；欄位與分組名稱只對應程式內建的 SQL 常數，不從輸入字串組進 SQL。
- 未宣告的參數（例如 `cursor`、`limit` 或其他資料集的分組參數）即使值為空也回 HTTP 422；值為空的已宣告參數視為沒有給；list endpoints 採同一規則，只是接受 `limit`、`cursor` 而不接受 series 的參數（[data-explorer.md](data-explorer.md) §7）。

### 5.2 回應 Schema

```json
{
  "bucket": "1d",
  "agg": "avg",
  "timezone": "Asia/Taipei",
  "series": [
    {
      "field": "load_mw",
      "unit": "MW",
      "group": {"subject": "nationwide"},
      "points": [
        {"t": "2026-11-20T00:00:00+08:00", "v": 30125.4},
        {"t": "2026-11-21T00:00:00+08:00", "v": null}
      ]
    }
  ]
}
```

- `bucket`：實際採用的粒度，不會是 `auto`。
- `agg`：實際採用的聚合；`bucket` 為 `raw` 時為 `null`。
- `series`：每個（欄位, 分組鍵值）一條，依欄位請求順序、再依分組鍵值排序。`group` 為分組欄位到值的對應，未分組時為 `{}`。
- `points`：依時間遞增。`t` 為 bucket 起點（`raw` 時為資料本身的時間，保留微秒），帶 `+08:00`；`v` 為數值，`null` 代表該 bucket 沒有資料（補值規則見 data-explorer.md §8）。不補值的資料集只回傳有值的點，不出現 `null`；窗口內沒有任何值的 series 不列出。
- `group` 中的時間值（例如鄉鎮預報的 `issued_at`）與 `t` 同格式，帶 `+08:00`。

### 5.3 上限與 HTTP 語意

| 情況 | 狀態碼 | `detail` |
| --- | --- | --- |
| 正常，含窗口內沒有資料 | 200 | —（沒有資料時 `series` 為 `[]`） |
| 手動指定的 `bucket` 讓任一 series 超過 1,200 點，或全部 series 合計超過 10,000 點 | 422 | `{"message": "...", "suggested_bucket": "1d"}`；`suggested_bucket` 為符合上限的最細粒度，沒有任何粒度符合時為 `null` |
| `auto` 也找不到符合上限的粒度 | 422 | 同上，`suggested_bucket` 為 `null` |
| 窗口超過 92 天、`start` 晚於 `end`、時間格式錯誤、未宣告的參數 | 422 | 字串訊息 |
| 欄位不在白名單、`bucket` 或 `agg` 不在列舉內（含 `agg=sum`） | 422 | FastAPI 驗證錯誤陣列 |
| TimescaleDB 無法連線 | 503 | `"Persistence unavailable"` |

點數以窗口內預期的 bucket 數計算：`raw` 依資料集節奏（逐時負載 1 小時、10 分鐘快照 10 分鐘），`1h` 與 `1d` 依整點與台北日界，含只涵蓋到部分的邊界 bucket。

### 5.4 各資料集

| 資料集 | 路徑 | `fields` 白名單（單位） | 分組 | 篩選 | 補值 |
| --- | --- | --- | --- | --- | --- |
| 逐時負載 | `GET /data/power/load/series` | `load_mw`（MW）。預設 `load_mw` | 固定依 `subject` | `subject` | 有（節奏 1 小時） |
| 全台供需 | `GET /data/power/supply-demand/series` | 功率（MW，萬瓩 × 10）：`curr_load_mw`、`real_hr_maxi_sply_capacity_mw`、`fore_maxi_sply_capacity_mw`、`fore_peak_dema_load_mw`、`fore_peak_resv_capacity_mw`、`yday_maxi_sply_capacity_mw`、`yday_peak_dema_load_mw`、`yday_peak_resv_capacity_mw`；百分比（%）：`curr_util_rate_pct`、`fore_peak_resv_rate_pct`、`yday_peak_resv_rate_pct`。預設 `curr_load_mw`、`real_hr_maxi_sply_capacity_mw` | 無（`group` 為 `{}`） | 無 | 有（節奏 10 分鐘） |
| 區域供需 | `GET /data/power/regional/series` | `load_mw`、`generation_mw`（MW，萬瓩 × 10）。預設 `load_mw` | 固定依 `region`，不提供四區合成 | `region`（四區之一，驗證同 list）；不接受 `completeness`（回 422）：完整度是逐一 10 分鐘時段的判定，`1h`／`1d` bucket 沒有對應的意義，不完整處改由 `null` 點與缺口清單揭露 | 有（節奏 10 分鐘）；某區缺少該時段時，該區的點為 `null` |
| 機組發電 | `GET /data/power/units/series` | `net_generation_mw`（MW，預設）、`capacity_mw`（MW） | `group_by=unit_type`（預設，依機組類型）或 `group_by=none`（所有成員的總和，`group` 為 `{}`） | `unit_type`、`unit_name`（精確比對，縮小合成的成員範圍） | 有（節奏 10 分鐘） |
| 測站觀測 | `GET /data/weather/observations/series` | `temperature_c`（°C，預設）、`relative_humidity_pct`（%）、`air_pressure_hpa`（hPa）、`precipitation_mm`（mm）、`wind_speed_m_s`（m/s） | 固定依 `station_id`；不接受 `group_by` | `station_id` | 有（節奏 1 小時） |
| 鄉鎮預報 | `GET /data/weather/forecasts/series` | `temperature_c`（°C，預設）、`apparent_temperature_c`（°C）、`dew_point_c`（°C）、`relative_humidity_pct`（%）、`probability_of_precipitation_pct`（%）、`wind_speed_m_s`（m/s） | 預設依 `geocode`；版本未隱含釘選時依 `geocode`、`dataset_id`、`issued_at` | `dataset_id`、`geocode`、`issued_at`、`source_updated_at`、`all_vintages` | 無 |
| CWA 觀測批次審計 | `GET /data/audits/cwa-observations/series` | 不接受；固定為 `batch_count`（`count`） | 固定依 `status` | `status`、`missing_station_id` | 無 |
| CWA 預報版本審計 | `GET /data/audits/cwa-forecasts/series` | 不接受；固定為 `version_count`（`count`） | 固定依 `status` | `dataset_id`、`status`、`missing_geocode` | 無 |

機組發電的每個點是成員合成後再做時間聚合的值：同一時點、同一分組的機組先加總（`NULL` 略過、不當成 0；全部為 `NULL` 時為 `null`），`1h`／`1d` 再對這些合計取 `avg`、`min` 或 `max`。儲能負載的負值照常加總，因此總和會扣掉充電功率。`auto` 以序列數計算點數：7 天窗口依 12 種 `unit_type` 分組時 `raw` 合計 12,108 點，超過 10,000，解析為 `1h`。

- **測站觀測**：觀測表沒有露點欄位，因此白名單不含露點；風向（`wind_direction_deg`）是方位角，平均值沒有意義，不列入。
- **鄉鎮預報**：時間軸為 `valid_from`。沒有指定 `issued_at`、`source_updated_at` 也沒有開啟 `all_vintages` 時，釘選最新發布版本（有 `dataset_id` 時取該預報產品的最新版本），每個 `geocode` 一條 series。沒有 `dataset_id` 時與 list 有一處不同：兩個預報產品常共用同一個最新 `issued_at`，而 `F-D0047-091` 的 `source_updated_at` 通常晚幾十秒，list 依 `source_updated_at` 會選到 12 小時區間的一週預報；series 在共用最新 `issued_at` 的版本中優先取逐時的 `F-D0047-089`，再比 `source_updated_at`。list 的解析不變，兩者集中於同一處屬 [#102](https://github.com/shiroki9979/shiro-mlops/issues/102) 的範圍，`group` 為 `{"geocode": ...}`。開啟 `all_vintages` 或指定版本篩選時，每個（`geocode`, `dataset_id`, `issued_at`）一條 series，`group` 帶這三個鍵；同一 `issued_at` 有多個更正版本時取 `source_updated_at` 最新者，有指定 `source_updated_at` 時改用該版本。兩個版本永不合併成同一條線。
- **鄉鎮預報的同時間多列**：同一版本、同一 `geocode`、同一 `valid_from` 可能有逐時列與三小時降雨機率列，各自只帶部分欄位；`raw` 取每個欄位在該時點的值。

#### CWA audit series

兩個 audit series 回傳狀態時間軸：每個 `status`（`complete`、`incomplete`）一條 series，`v` 為該 bucket 內的批次數（依 `fetched_at`）或版本數（依 `issued_at`，版本以 `dataset_id`、`issued_at`、`source_updated_at` 識別）。`status` 由各批次或版本的缺漏清單（`missing_station_ids`、`missing_geocodes`）推導：清單為空為 `complete`，否則為 `incomplete`；list 項目的 `status`、`status` 篩選與 `GET /data/status` 的完整度採同一推導；header 表不保存完整度欄位。

- 不接受 `fields` 與 `agg`，帶了就回 HTTP 422（未宣告的參數）；回應的 `agg` 固定為 `null`。
- `1h`、`1d` 的 `v` 為該 bucket 的列數；`raw` 時每個批次或版本各是一個 `v = 1` 的點，`issued_at` 相同的版本各自成點，因此 `t` 可能重複。
- 不補值：沒有批次或版本的 bucket 不出現；某狀態在窗口內沒有任何列時，不回傳該狀態的 series。
- 篩選與 list 相同，`status` 只接受 `complete` 或 `incomplete`，其他值回 HTTP 422；篩選比對的是推導出的 `status`。點數上限依 §5.3，`raw` 以 1 小時節奏估算。

```json
{
  "bucket": "1h",
  "agg": null,
  "timezone": "Asia/Taipei",
  "series": [
    {"field": "batch_count", "unit": "count", "group": {"status": "complete"},
     "points": [{"t": "2026-11-21T10:00:00+08:00", "v": 2}]},
    {"field": "batch_count", "unit": "count", "group": {"status": "incomplete"},
     "points": [{"t": "2026-11-21T10:00:00+08:00", "v": 1}]}
  ]
}
```
