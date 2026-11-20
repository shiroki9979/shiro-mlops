# API 介面規格 (REST Interface)

- 建立日期：2026-11-20
- 最後更新：2026-11-20
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

## 2. 就緒狀態檢查

- **路徑**：`GET /tasks/{task_id}/ready`；`GET /ready` 為動態視界預報任務 `dynamic_horizon_forecast` 的別名，回應與 `GET /tasks/dynamic_horizon_forecast/ready` 相同。
- **未知任務**：`task_id` 不在已部署任務設定中時回傳 HTTP 404。
- **回應 Body**：`status`（`ready` 或 `not_ready`）、`mode`、`model_loaded`（該任務）、`reason`。
- **語意**：模型已載入、負載起點未過舊，且預報天氣任務的正常或降級氣象來源可涵蓋完整 168 小時時回傳 HTTP 200；body 必須揭露 `mode: normal` 或 `mode: degraded`。模型或必要資料不足、或負載起點過舊時回傳 HTTP 503，並列出未就緒原因。
- **觀測天氣任務**（任務類型 `requirements().weather` 為 `OBSERVED`，例如 `load_pattern_anomaly`）：不讀預報、不降級；模型已載入、負載起點未過舊，且錨點結束小時有完整的負載與測站觀測評分窗時回傳 HTTP 200 與 `mode: normal`，否則回傳 HTTP 503。
- **負載起點過舊**：最新推算列（`source = 'regional_snapshot_sum'`）的 `raw_taipower_load.time` 早於請求時間超過任務設定 `[policies].stale_anchor_max_lag_hours`（預設 `3`）小時；此狀態不降級，`/ready` 與 `/predict` 皆回傳 HTTP 503。
- **模型**：API 啟動時依任務設定逐一載入 `DATA_DIR/models/<task_id>/`（[ML 任務設定 §4](ml-tasks.md#4-模型保存tasksmodel_storepy)）；單一任務的模型目錄不存在或無法載入時，只有該任務維持 `not_ready`（載入錯誤寫入日誌），其他任務照常服務。既有 `DATA_DIR/model.joblib` 不載入，首次以新格式重新訓練前 `/ready` 維持 `not_ready`。任務設定無效時 API 啟動失敗。
- 空資料庫首次啟動時 API process 可存活，但不得由 API lifespan 直接呼叫 CWA 或以測試資料建立正式模型。

## 3. 隨需動態視界負載預報

- **路徑**：`POST /predict`（動態視界預報任務 `dynamic_horizon_forecast` 的別名，與 §4 共用 runner `predict_task` 與錯誤對應；預測 item 即該任務的 item（`PredictionItem`：`datetime`、`predicted_load_mw`、`temperature`、`relative_humidity`、`weather_sources`），同一請求的 `predictions` 與 `POST /tasks/dynamic_horizon_forecast/predict` 相同）
- **預測對象**：固定為 `nationwide`，並於回應 `subject` 揭露；模型只預測全台負載，不宣稱支援區域負載模型。
- **相容性欄位**：請求 `location` 為選填，於 OpenAPI 標示 `deprecated`；任何值皆被忽略，不影響預測對象，也不再回傳 HTTP 400。回應不再包含 `location`。
- **資料來源**：只讀 canonical TimescaleDB tables。負載歷史與遞迴起點只取 `source = 'regional_snapshot_sum'` 的列，`source IS NULL` 的 d015046 舊列一律忽略。氣象以請求時間為 `as_of`：只採用請求當下已發布且已更新的預報版本；某數值沒有發布未超過七小時的預報版本可提供時（以提供該數值的版本判定，[資料契約 §3.3](data-contracts.md#33-cwa-預報版本選取與逐時投影)），該數值依序退回氣象代表點測站的前日同小時觀測、同月份同小時歷史平均，並回傳 `mode: "degraded"`；替代資料皆不存在，或負載起點過舊（§2）時回傳 HTTP 503。
- **狀態欄位**：`status` 表示請求成功（固定為 `success`）；`mode` 表示預報品質（`normal` 或 `degraded`），兩者不得混用。
- **不寫入已發布預報**：隨需預報只讀不寫；已發布預報只由每小時的 `issued_forecast_schedule` 產生（[Dagster 排程](dagster-schedules.md)、ADR-0013）。
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

## 4. 通用任務推論

- **路徑**：`POST /tasks/{task_id}/predict`（ADR-0009）
- **請求 Body**：`horizon_hours`（整數 1–168，預設 24）；不接受 `location`。語意依任務的天氣輸入而定：
  - 預報天氣任務（`FORECAST`）：負載起點之後預測的小時數（預測視界）。
  - 觀測天氣任務（`OBSERVED`）：評分最近幾個時間窗結束小時，由負載起點往回算，即結束小時落在 `(anchor - horizon_hours, anchor]`；不預測未來。資料有缺口的時間窗不評分，因此回傳筆數可能少於 `horizon_hours`，但不以常數補值。
- **回應 Body**：共通欄位 `status`（固定為 `success`）、`task_id`、`task_type`、`subject`、`mode`，以及 `predictions`；`predictions` 的 item schema 由任務類型的 `prediction_item` 與任務設定的 `weather.fields` 共同決定（[ML 任務設定 §2](ml-tasks.md#2-任務類型介面taskstypes)），OpenAPI 以每個任務的 `<TaskId>TaskPredictionResponse`（item 為 `<TaskId>PredictionItem`，未附帶天氣者直接沿用任務類型的 item）逐一描述，並以 `task_id` 常數區分；回應模型於建構時驗證，端點不再以聯集重驗。
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
