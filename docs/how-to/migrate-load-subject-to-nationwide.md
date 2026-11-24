# 如何將全台負載的預測對象遷移為 nationwide

- 建立日期：2026-09-27
- 最後更新：2026-11-24

> [!NOTE]
> **Diátaxis 象限鎖定**
>
> - **目標象限**：How-To Guide
> - **目標讀者**：負責既有 TimescaleDB volume 升級的操作人員
> - **核心目標**：把 `raw_taipower_load` 的 `location` 欄改名為 `subject`，並將既有 `Taipei` 列遷移為 `nationwide`，過程中不遺失無法回補的全台逐時實際負載
> - **排除內容（Avoid）**：預測對象與氣象代表點分離的設計理由（見 [ADR-0009](../adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md)）、欄位契約（見 [資料契約 §3](../reference/data-contracts.md#3-地端時序資料庫模型-timescaledb-hypertables)）

本指南適用於在 ADR-0009 之前就已建立 `raw_taipower_load` 的資料庫。全新資料庫建立時已直接採用 `subject`，不需執行本指南。

新版服務啟動時也會以同一組語句自動遷移，且可重複執行；本指南改為手動先行遷移，是為了控制順序：遷移後舊版程式仍以 `location` 讀寫，若排程仍在運作，會在新版部署前持續失敗或寫入 `Taipei`。因此必須依「停止排程 → 套用遷移 → 部署新版 → 重啟」執行。

---

## 1. 前置需求

- 可存取 Dagster UI（`http://localhost:3000`）與 `shiro_postgres` 容器。以下指令預設使用 `.env.example` 的 `TIMESCALE_USER=postgres` 與 `TIMESCALE_DB=shiro_timeseries`，若本機設定不同請替換。
- 已取得含 ADR-0009 預測對象遷移的新版程式碼，但尚未部署。
- 預留的停機時間短於 `HOURLY_LOAD_CATCHUP_MAX_HOURS`（預設 168 小時）。`hourly_actual_load_job` 恢復後會從最後一個已推算小時之後補算到現在，最多回溯此長度；停機超過此長度時，請見第 6 節補算。

---

## 2. 停止會讀寫 `raw_taipower_load` 的排程

1. 在 Dagster UI 的 **Automation** 頁面停用下列排程：
   - `hourly_actual_load_schedule`
   - `daily_training_schedule`（新版改名為 `dynamic_horizon_forecast__training_schedule`）
   - `hourly_drift_schedule`（新版改名為 `dynamic_horizon_forecast__monitoring_schedule`）
2. 在 **Runs** 頁面確認 `hourly_actual_load_job`、`daily_training_job`、`hourly_drift_job` 沒有執行中的 run；有的話等待結束。

`taipower_supply_demand_snapshot_schedule` 與兩個 CWA 擷取排程**保持啟用**：它們只寫入快照與氣象資料表，且區域快照無法回補，停用會造成永久缺口。

---

## 3. 盤點遷移前的資料列

```bash
docker exec shiro_postgres psql -U postgres -d shiro_timeseries -c \
  "SELECT location, COUNT(*) AS rows, MIN(time) AS first_time, MAX(time) AS last_time
   FROM raw_taipower_load GROUP BY location ORDER BY location;"
```

預期只有 `Taipei` 一列。記下筆數，後續用來比對。若回報 `column "location" does not exist`，表示本資料庫已完成遷移，直接跳到第 5 節。

---

## 4. 在交易中套用遷移

開啟互動式 psql：

```bash
docker exec -it shiro_postgres psql -U postgres -d shiro_timeseries
```

依序執行：

```sql
BEGIN;
ALTER TABLE raw_taipower_load RENAME COLUMN location TO subject;
UPDATE raw_taipower_load SET subject = 'nationwide' WHERE subject = 'Taipei';
```

確認 psql 回報的 `UPDATE <n>` 與第 3 節 `Taipei` 的筆數相同。相同時繼續：

```sql
COMMIT;
```

筆數不符時執行 `ROLLBACK;`，回到第 3 節重新盤點。

---

## 5. 部署新版並重啟服務

1. 在部署目錄切換到新版程式碼（例如 `git pull`）。
2. 重建並重啟容器，讓 API 與 Dagster 載入新版：

   ```bash
   make compose-up
   ```

3. 確認遷移結果與新版寫入：

   ```bash
   docker exec shiro_postgres psql -U postgres -d shiro_timeseries -c \
     "SELECT subject, COUNT(*) AS rows, MAX(time) AS last_time
      FROM raw_taipower_load GROUP BY subject ORDER BY subject;"
   ```

   預期只有 `nationwide` 一列，筆數等於第 3 節的筆數。
4. 在 Dagster UI 手動 materialize `raw_taipower_load` 一次，確認 run 成功，且重跑上一步查詢時仍只有 `nationwide`。
5. 重新啟用 `hourly_actual_load_schedule`，並開啟新版的 `dynamic_horizon_forecast__training_schedule` 與 `dynamic_horizon_forecast__monitoring_schedule`。新版以資產工廠產生每個任務的資產與排程，舊的 `daily_training_schedule` 與 `hourly_drift_schedule` 已不存在，新排程預設為停用。
6. 手動啟動一次 `dynamic_horizon_forecast__training_job`。Dagster 不會把舊資產 `trained_forecaster_model` 的 materialization 轉給新資產 `dynamic_horizon_forecast__model`，第一次訓練成功前監控排程會略過。

---

## 6. 停機超過補算上限時補算缺口

區域快照在停機期間持續累積，缺少的只是推算結果。`hourly_actual_load_job` 的 run log 會以 warning 列出超出 `HOURLY_LOAD_CATCHUP_MAX_HOURS` 而未推算的區間；以該區間（台灣本地時間）執行一次性重算腳本，先以 `--dry-run` 確認將寫入的小時：

```bash
uv run python scripts/rederive_hourly_actual_load.py \
  --start 2026-09-20T03:00:00 --end 2026-09-26T14:00:00 --dry-run
```

確認無誤後去掉 `--dry-run` 再執行一次。腳本只讀已入庫的區域快照、只寫入尚無資料的小時，不覆寫既有列。`--start` 與 `--end` 須為不帶 UTC offset 的整點；落在小時中間的時刻會被拒絕，否則該小時只會以之後的樣本推算並寫入。

完成後，Data Explorer 的逐時用電負載頁（`/data/power/load`）不應再列出停機期間的缺口。
