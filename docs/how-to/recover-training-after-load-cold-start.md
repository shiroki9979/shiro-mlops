# 如何在逐時負載冷啟動後恢復訓練與監控排程

- 建立日期：2026-09-26
- 最後更新：2026-09-27

> [!NOTE]
> **Diátaxis 象限鎖定**
>
> - **目標象限**：How-To Guide
> - **目標讀者**：負責地端 Docker Compose Stack 的操作人員
> - **核心目標**：從空的 `raw_taipower_load` 開始累積全台逐時實際負載，確認累積進度，並在門檻達成後讓 `dynamic_horizon_forecast__training_job` 與 `dynamic_horizon_forecast__monitoring_job` 恢復運作
> - **排除內容（Avoid）**：推算規則與 28 日門檻的設計理由（見 [ADR-0008](../adr/0008-derive-hourly-actual-load-from-regional-snapshots.md)）、排程與失敗政策契約（見 [SPEC §3](../SPEC.md)）

全台逐時實際負載只能由區域供需快照往後累積，無法回補歷史。有效逐時觀測未達任務設定 `src/shiro_mlops/tasks/dynamic_horizon_forecast.toml` 的 `[policies].min_training_hours`（預設 `672`，即 28 日）前，訓練與 drift 排程每次 tick 都會略過並揭露原因，這是預期行為。

---

## 1. 前置需求

- 已依 [如何在全地端運行完整 MLOps 容器化環境](run-full-local-stack.md) 啟動 Compose Stack。
- 既有資料庫已依 [如何移除 d015046 時期的舊負載資料列](remove-legacy-d015046-load-rows.md) 清除 `source IS NULL` 的舊列。舊列存在時訓練會被拒絕；全新資料庫不需處理。

---

## 2. 開啟累積與下游排程

在 `http://localhost:3000` 的 **Automation** 頁面開啟下列六個排程。Dagster 排程預設為停用，未開啟的排程不會累積任何資料：

| 排程 | 作用 |
| :--- | :--- |
| `taipower_supply_demand_snapshot_schedule` | 每 10 分鐘保存區域快照，逐時負載的唯一來源 |
| `hourly_actual_load_schedule` | 每小時第 5 分鐘推算最近已結束小時並寫入 `raw_taipower_load` |
| `cwa_observation_ingestion_job_schedule` | 每小時第 10 分鐘保存 CWA 測站觀測 |
| `cwa_forecast_ingestion_job_schedule` | 每小時第 40 分鐘保存 CWA 鄉鎮預報版本 |
| `dynamic_horizon_forecast__training_schedule` | 台灣時間 00:00 訓練；門檻未達時略過 |
| `dynamic_horizon_forecast__monitoring_schedule` | 每小時整點產生監控報告；門檻未達或尚無模型時略過 |

任務的訓練與監控排程可以在冷啟動當天就開啟，不需等待累積完成。

---

## 3. 執行 smoke check 確認排程與累積進度

在專案根目錄執行：

```bash
make smoke-check
```

等同於：

```bash
docker compose -f docker/docker-compose.yml exec dagster-webserver \
  python -m shiro_mlops.pipelines.smoke_check
```

此指令只讀取 Dagster instance 與 TimescaleDB，不寫入資料、不呼叫外部 API，也不啟動 run，可隨時重複執行。

累積期間的預期輸出：

```text
[PASS] schedule taipower_supply_demand_snapshot_schedule: ... running
...（其餘五個排程皆為 PASS）
[PASS] job dynamic_horizon_forecast__training_job: reads raw_taipower_load via dynamic_horizon_forecast__features
[PASS] job dynamic_horizon_forecast__monitoring_job: reads raw_taipower_load via dynamic_horizon_forecast__monitoring
[WAIT] dynamic_horizon_forecast load accumulation: Insufficient hourly actual load for training: 130 valid hourly observations; 672 required (policies.min_training_hours). 542 more hours needed (at least 22.6 days of accumulation).
[PASS] dynamic_horizon_forecast load freshness: latest derived hour 2026-10-01T13:00:00 lags 2026-10-01T14:20:00 by 1:20:00
[WAIT] tick dynamic_horizon_forecast__training_schedule: would skip: Insufficient hourly actual load ...
[WAIT] tick dynamic_horizon_forecast__monitoring_schedule: would skip: Insufficient hourly actual load ...
Summary: 9 pass, 3 wait, 0 fail
```

`WAIT` 表示仍在累積，指令結束碼為 `0`；任何 `FAIL` 都會讓結束碼為 `1`，處理方式見第 6 節。

累積期間建議每日執行一次，確認 `valid hourly observations` 持續增加且 `dynamic_horizon_forecast load freshness` 維持 `PASS`。

---

## 4. 預估累積完成時間

- 每個有效小時需要至少 `HOURLY_LOAD_MIN_SAMPLES`（預設 `4`）個四區齊全的 10 分鐘樣本；未達者該小時留空、不內插，也不計入門檻。
- 連續無缺漏時約需 28 日；每個缺值小時都會讓完成時間往後延一小時。
- smoke check 回報的 `at least N days` 以剩餘小時全部有效估算，是最短等待時間。

---

## 5. 確認恢復並完成第一次訓練

1. 門檻達成後執行：

   ```bash
   make smoke-check ARGS=--require-ready
   ```

   `dynamic_horizon_forecast load accumulation` 與 `tick dynamic_horizon_forecast__training_schedule` 應轉為 `PASS`，此時 `tick dynamic_horizon_forecast__monitoring_schedule` 仍為 `WAIT`（原因為尚無 `dynamic_horizon_forecast__model` materialization），因此結束碼仍為 `1`。
2. 依 [全地端環境指南第 4 節](run-full-local-stack.md#4-準備資料並訓練模型) 手動啟動 `dynamic_horizon_forecast__training_job`，不需等待台灣時間 00:00 的排程自然觸發。
3. 訓練成功後重跑 `make smoke-check ARGS=--require-ready`，預期所有項目皆為 `PASS` 且結束碼為 `0`。下一個整點起 `dynamic_horizon_forecast__monitoring_job` 會自動觸發。
4. 執行 `docker compose -f docker/docker-compose.yml restart api` 載入 `data/models/dynamic_horizon_forecast/` 的新模型，再以 `curl -i http://localhost:8000/ready` 確認回傳 HTTP 200。既有的 `data/model.joblib` 已失效且不再載入（ADR-0010），因此第一次訓練完成前 `/ready` 一律為 `not_ready`。

---

## 6. 預期失敗邊界與處理

| 情境 | 可見位置 | 系統行為 | 處理方式 |
| :--- | :--- | :--- | :--- |
| 有效逐時觀測少於 `[policies].min_training_hours` | 排程 tick 的 skip 訊息；smoke check `WAIT` | 訓練與監控略過；手動執行 `dynamic_horizon_forecast__training_job` 時 `dynamic_horizon_forecast__features` 以 `Insufficient hourly actual load` 失敗，metadata 附 `valid_hours`／`required_hours`，不產出模型 | 繼續累積，不要以 fixture 或其他口徑資料補足 |
| `raw_taipower_load` 仍有 `source IS NULL` 舊列 | 同上，訊息含 `legacy rows` | 即使筆數足夠也拒絕訓練 | 依 [舊列清除指南](remove-legacy-d015046-load-rows.md) 處理 |
| 門檻已達但尚無模型 | `dynamic_horizon_forecast__monitoring_schedule` skip 訊息 | 監控略過 | 完成第 5 節的第一次訓練 |
| 最新推算小時落後超過 `[policies].stale_anchor_max_lag_hours` | smoke check `dynamic_horizon_forecast load freshness` `FAIL` | 累積停滯；`/ready` 與 `/predict` 同時回 HTTP 503 | 檢查 `taipower_supply_demand_snapshot_job` 與 `hourly_actual_load_job` 最近 run 是否失敗；停擺期間錯過的快照永久缺失 |
| 排程未開啟 | smoke check `schedule ...` `FAIL` | 該排程不會 tick | 依第 2 節開啟 |
| smoke check 回報 job 邊界 `FAIL` | `job dynamic_horizon_forecast__training_job`／`job dynamic_horizon_forecast__monitoring_job` | 部署的程式碼會讓訓練或監控執行擷取資產 | 停用這兩個排程，確認 `/workspace` 掛載的程式碼版本後執行 `docker compose -f docker/docker-compose.yml restart dagster-webserver` |
| 無法連線 TimescaleDB | smoke check 各 readiness 項目 `FAIL`；Dagster tick 錯誤 | 訓練與監控排程 tick 失敗、不啟動 run | 以 `docker compose -f docker/docker-compose.yml ps` 確認 `shiro_postgres` 健康狀態 |

累積停滯造成的缺口無法回補，只會延後門檻達成時間；恢復擷取後不需要額外操作，累積會自動接續。
