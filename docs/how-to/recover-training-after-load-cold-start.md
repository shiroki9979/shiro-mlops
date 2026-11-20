# 如何在逐時負載冷啟動後恢復訓練與監控排程

- 建立日期：2026-09-26
- 最後更新：2026-11-20

> [!NOTE]
> **Diátaxis 象限鎖定**
>
> - **目標象限**：How-To Guide
> - **目標讀者**：負責地端 Docker Compose Stack 的操作人員
> - **核心目標**：從空的 `raw_taipower_load` 開始累積全台逐時實際負載，確認累積進度，並在門檻達成後讓 `dynamic_horizon_forecast__training_job` 與 `dynamic_horizon_forecast__monitoring_job` 恢復運作，首次訓練成功後開啟 `issued_forecast_schedule` 每小時發布預報，並從冷啟動當天起以 `forecast_track_record_schedule` 每小時彙整預報實績
> - **排除內容（Avoid）**：推算規則與 28 日門檻的設計理由（見 [ADR-0008](../adr/0008-derive-hourly-actual-load-from-regional-snapshots.md)）、排程與失敗政策契約（見 [Dagster 排程](../reference/dagster-schedules.md)）

全台逐時實際負載只能由區域供需快照往後累積，無法回補歷史。有效逐時觀測未達任務設定 `src/shiro_mlops/tasks/dynamic_horizon_forecast.toml` 的 `[policies].min_training_hours`（預設 `672`，連續無缺漏時約 28 日）前，訓練與 drift 排程每次 tick 都會略過並揭露原因，這是預期行為。

---

## 1. 前置需求

- 已依 [如何在全地端運行完整 MLOps 容器化環境](run-full-local-stack.md) 啟動 Compose Stack。
- 既有資料庫已依 [如何移除 d015046 時期的舊負載資料列](remove-legacy-d015046-load-rows.md) 清除 `source IS NULL` 的舊列。舊列存在時訓練會被拒絕；全新資料庫不需處理。

---

## 2. 開啟累積與下游排程

在 `http://localhost:3000` 的 **Automation** 頁面開啟下列排程。Dagster 排程預設為停用，未開啟的排程不會累積任何資料：

| 排程 | 作用 |
| :--- | :--- |
| `taipower_supply_demand_snapshot_schedule` | 每 10 分鐘保存區域快照，逐時負載的唯一來源 |
| `hourly_actual_load_schedule` | 每小時第 5 分鐘推算最近已結束小時並寫入 `raw_taipower_load` |
| `cwa_observation_ingestion_job_schedule` | 每小時第 10 分鐘保存 CWA 測站觀測 |
| `cwa_forecast_ingestion_job_schedule` | 每小時第 40 分鐘保存 CWA 鄉鎮預報版本 |
| `forecast_track_record_schedule` | 每小時第 25 分鐘彙整預報實績；尚無已發布預報時照常成功，累積天數為 0 |
| `dynamic_horizon_forecast__training_schedule` | 台灣時間 00:00 訓練；門檻未達時略過 |
| `dynamic_horizon_forecast__monitoring_schedule` | 每小時整點產生監控報告；門檻未達或尚無模型時略過 |
| `high_load_alert__training_schedule` | 台灣時間 00:30 訓練高負載預警模型；門檻（1344 小時）未達時略過 |
| `high_load_alert__monitoring_schedule` | 每小時第 5 分鐘產生監控報告；門檻未達或尚無模型時略過 |
| `load_pattern_anomaly__training_schedule` | 台灣時間 01:00 訓練用電型態異常偵測模型；門檻未達時略過 |
| `load_pattern_anomaly__monitoring_schedule` | 每小時整點產生監控報告；門檻未達或尚無模型時略過 |

任務的訓練與監控排程可以在冷啟動當天就開啟，不需等待累積完成。預報實績排程 `forecast_track_record_schedule` 與擷取排程一起開啟：發布開始前，每次彙整的 materialization metadata 皆為 `accumulated_days = 0`，這是預期結果；發布開始後逐日增加。發布排程 `issued_forecast_schedule` 此時保持停用，待第 5 節首次訓練成功後才開啟。

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

累積期間的預期輸出（節錄，三個已部署任務）：

```text
[PASS] schedule taipower_supply_demand_snapshot_schedule: ... running
...（其餘三個擷取排程皆為 PASS）
[WAIT] schedule issued_forecast_schedule: issued_forecast_job at '15 * * * *' (Asia/Taipei) is registered but not running; turn it on in the Dagster UI after the first successful training run
[PASS] schedule forecast_track_record_schedule: forecast_track_record_job at '25 * * * *' (Asia/Taipei), running
...（六個任務排程與六個任務 job 皆為 PASS）
[WAIT] dynamic_horizon_forecast load accumulation: Insufficient hourly actual load for training: 130 valid hourly observations; 672 required (policies.min_training_hours). 542 more hours needed (at least 22.6 days of accumulation).
[PASS] dynamic_horizon_forecast load freshness: latest derived hour 2026-10-01T13:00:00 lags 2026-10-01T14:20:00 by 1:20:00
[WAIT] tick dynamic_horizon_forecast__training_schedule: would skip: Insufficient hourly actual load ...
[WAIT] tick dynamic_horizon_forecast__monitoring_schedule: would skip: Insufficient hourly actual load ...
...（high_load_alert 與 load_pattern_anomaly 同樣為累積 WAIT、新鮮度 PASS、兩個 tick WAIT）
[WAIT] tick issued_forecast_schedule: would skip: No dynamic_horizon_forecast__model materialization yet; issued_forecast_schedule waits for the first successful training run.
Summary: 20 pass, 11 wait, 0 fail
```

`WAIT` 表示仍在累積，或發布排程依本指南刻意停用，指令結束碼為 `0`；任何 `FAIL` 都會讓結束碼為 `1`，處理方式見第 6 節。發布排程的兩個項目與預報實績排程不受 `--task` 篩選，與擷取排程相同。

累積期間建議每日執行一次，確認 `valid hourly observations` 持續增加且 `dynamic_horizon_forecast load freshness` 維持 `PASS`。

---

## 4. 預估累積完成時間

- 每個有效小時需要至少 `HOURLY_LOAD_MIN_SAMPLES`（預設 `4`）個四區齊全的 10 分鐘樣本；未達者該小時留空、不內插，也不計入門檻。
- 連續無缺漏時約需 28 日；每個缺值小時都會讓完成時間往後延一小時。
- smoke check 回報的 `at least N days` 以剩餘小時全部有效估算，是最短等待時間。

---

## 5. 確認恢復並完成第一次訓練

1. 門檻達成後，以 `--task` 只檢查該任務與共用擷取排程：

   ```bash
   make smoke-check ARGS="--require-ready --task dynamic_horizon_forecast"
   ```

   各任務門檻不同（`high_load_alert` 需 1344 小時），不帶 `--task` 時，尚在累積的其他任務會以 `WAIT` 讓結束碼維持 `1`。`dynamic_horizon_forecast load accumulation` 與 `tick dynamic_horizon_forecast__training_schedule` 應轉為 `PASS`，此時 `tick dynamic_horizon_forecast__monitoring_schedule` 與 `tick issued_forecast_schedule` 仍為 `WAIT`（原因為尚無 `dynamic_horizon_forecast__model` materialization），`schedule issued_forecast_schedule` 也仍為 `WAIT`（尚未開啟），因此結束碼仍為 `1`。
2. 依 [全地端環境指南第 4 節](run-full-local-stack.md#4-準備資料並訓練模型) 手動啟動已達門檻任務的 `<task_id>__training_job`（`dynamic_horizon_forecast` 與 `load_pattern_anomaly` 需 672 小時，`high_load_alert` 需 1344 小時），不需等待排程自然觸發。smoke check 逐一列出每個已部署任務的項目，各任務的 `tick ...__monitoring_schedule` 都要有該任務的模型才會轉為 `PASS`。
3. `dynamic_horizon_forecast__training_job` 成功後重跑同一指令，預期 `tick dynamic_horizon_forecast__monitoring_schedule` 與 `tick issued_forecast_schedule` 轉為 `PASS`（`would request a run`），只剩 `schedule issued_forecast_schedule` 為 `WAIT`，結束碼仍為 `1`。下一個整點起 `dynamic_horizon_forecast__monitoring_job` 會自動觸發。
4. 在 **Automation** 頁面開啟 `issued_forecast_schedule`，再重跑同一指令，預期所有項目皆為 `PASS` 且結束碼為 `0`。之後每小時第 15 分鐘由 `issued_forecast_job` 寫入一份已發布預報；未開啟的每一小時都不會留下已發布預報，事後也無法回補，因此首次訓練成功後應立即開啟。發布排程只發布 `dynamic_horizon_forecast`，其他任務達門檻並完成首次訓練後，以各自的 `--task <task_id>` 驗收，全部就緒時不帶 `--task` 的 `--require-ready` 才會回傳 `0`。
5. 執行 `docker compose -f docker/docker-compose.yml restart api` 載入 `data/models/<task_id>/` 的新模型，再以 `curl -i http://localhost:8000/ready` 與 `curl -i http://localhost:8000/tasks/load_pattern_anomaly/ready` 確認回傳 HTTP 200。既有的 `data/model.joblib` 已失效且不再載入（ADR-0010），因此第一次訓練完成前 `/ready` 一律為 `not_ready`。

---

## 6. 預期失敗邊界與處理

| 情境 | 可見位置 | 系統行為 | 處理方式 |
| :--- | :--- | :--- | :--- |
| 有效逐時觀測少於 `[policies].min_training_hours` | 排程 tick 的 skip 訊息；smoke check `WAIT` | 訓練與監控略過；手動執行 `dynamic_horizon_forecast__training_job` 時 `dynamic_horizon_forecast__features` 以 `Insufficient hourly actual load` 失敗，metadata 附 `valid_hours`／`required_hours`，不產出模型 | 繼續累積，不要以 fixture 或其他口徑資料補足 |
| `raw_taipower_load` 仍有 `source IS NULL` 舊列 | 同上，訊息含 `legacy rows` | 即使筆數足夠也拒絕訓練 | 依 [舊列清除指南](remove-legacy-d015046-load-rows.md) 處理 |
| 門檻已達但尚無模型 | `dynamic_horizon_forecast__monitoring_schedule` 與 `issued_forecast_schedule` skip 訊息；smoke check `tick issued_forecast_schedule` `WAIT` | 監控與發布略過 | 完成第 5 節的第一次訓練 |
| 最新推算小時落後超過 `[policies].stale_anchor_max_lag_hours` | smoke check `dynamic_horizon_forecast load freshness` `FAIL` | 累積停滯；`/ready` 與 `/predict` 同時回 HTTP 503 | 檢查 `taipower_supply_demand_snapshot_job` 與 `hourly_actual_load_job` 最近 run 是否失敗；停擺期間錯過的快照永久缺失 |
| 擷取、預報實績或任務排程未開啟 | smoke check `schedule ...` `FAIL` | 該排程不會 tick；預報實績排程未開啟時，彙整停在最後一次執行的統計截至時刻 | 依第 2 節開啟；預報實績排程開啟後，下一個 tick 即計入期間的已發布預報 |
| 預報實績排程未註冊或 cron 不符 | smoke check `schedule forecast_track_record_schedule` `FAIL` | 部署的程式碼與 [Dagster 排程](../reference/dagster-schedules.md) 契約不符 | 確認 `/workspace` 掛載的程式碼版本後執行 `docker compose -f docker/docker-compose.yml restart dagster-webserver` |
| 發布排程未開啟 | smoke check `schedule issued_forecast_schedule` `WAIT`；`--require-ready` 結束碼為 `1` | 不寫入已發布預報，缺漏的小時無法回補 | 首次訓練成功後依第 5 節步驟 4 開啟 |
| 發布排程未註冊或 cron 不符 | smoke check `schedule issued_forecast_schedule` `FAIL` | 部署的程式碼與 [Dagster 排程](../reference/dagster-schedules.md) 契約不符 | 確認 `/workspace` 掛載的程式碼版本後執行 `docker compose -f docker/docker-compose.yml restart dagster-webserver` |
| smoke check 回報 job 邊界 `FAIL` | `job dynamic_horizon_forecast__training_job`／`job dynamic_horizon_forecast__monitoring_job` | 部署的程式碼會讓訓練或監控執行擷取資產 | 停用這兩個排程，確認 `/workspace` 掛載的程式碼版本後執行 `docker compose -f docker/docker-compose.yml restart dagster-webserver` |
| 無法連線 TimescaleDB | smoke check 各 readiness 項目 `FAIL`；Dagster tick 錯誤 | 訓練與監控排程 tick 失敗、不啟動 run | 以 `docker compose -f docker/docker-compose.yml ps` 確認 `shiro_postgres` 健康狀態 |

累積停滯造成的缺口無法回補，只會延後門檻達成時間；恢復擷取後不需要額外操作，累積會自動接續。
