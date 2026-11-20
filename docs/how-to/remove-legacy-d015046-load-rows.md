# 如何移除 d015046 時期的舊負載資料列

- 建立日期：2026-09-26
- 最後更新：2026-11-20

> [!NOTE]
> **Diátaxis 象限鎖定**
>
> - **目標象限**：How-To Guide
> - **目標讀者**：負責既有 TimescaleDB volume 升級的操作人員
> - **核心目標**：在啟用 `hourly_actual_load_schedule` 前，確認並清除 `raw_taipower_load` 中 d015046 時期的資料列，並補上 `source` 的 `NOT NULL` 約束
> - **排除內容（Avoid）**：推算規則的設計理由（見 [ADR-0008](../adr/0008-derive-hourly-actual-load-from-regional-snapshots.md)）、欄位契約（見 [資料契約 §3](../reference/data-contracts.md#3-地端時序資料庫模型-timescaledb-hypertables)）

本指南適用於在 ADR-0008 之前就已建立 `raw_taipower_load` 的資料庫。全新資料庫建立時 `source` 已是 `NOT NULL`，不需執行本指南。

升級後的服務啟動時會為既有表補上可為 `NULL` 的 `source` 欄位，但不會改寫或刪除任何列。`source IS NULL` 的列即為 d015046 時期的資料；推算寫入的列一律標記為 `regional_snapshot_sum`。清除必須由操作人員確認後手動執行。

---

## 1. 前置需求

- 已部署含 `hourly_actual_load_job` 的版本，且 Dagster 或 API 服務至少啟動過一次（完成 `source` 欄位升級）。
- `hourly_actual_load_schedule` 維持停用；清除完成前不要開啟。
- 可存取 `shiro_postgres` 容器。以下指令預設使用 `.env.example` 的 `TIMESCALE_USER=postgres` 與 `TIMESCALE_DB=shiro_timeseries`，若本機設定不同請替換。

---

## 2. 確認 `source` 欄位已補上

```bash
docker exec shiro_postgres psql -U postgres -d shiro_timeseries -c \
  "SELECT column_name, is_nullable FROM information_schema.columns
   WHERE table_name = 'raw_taipower_load' AND column_name = 'source';"
```

預期回傳一列 `source | YES`。若沒有回傳任何列，先重新啟動 Dagster 或 API 服務再重試。若已是 `NO`，表示本資料庫已完成清除，停止執行本指南。

---

## 3. 盤點待清除的資料列

```bash
docker exec shiro_postgres psql -U postgres -d shiro_timeseries -c \
  "SELECT COALESCE(source, '<NULL: d015046>') AS source, COUNT(*) AS rows,
          MIN(time) AS first_time, MAX(time) AS last_time
   FROM raw_taipower_load GROUP BY source ORDER BY source;"
```

記下 `<NULL: d015046>` 那一列的筆數與時間範圍，後續刪除時用來比對。若該列不存在，直接跳到第 6 節。

---

## 4. 匯出待清除資料列作為備份

```bash
docker exec shiro_postgres psql -U postgres -d shiro_timeseries -c \
  "\copy (SELECT * FROM raw_taipower_load WHERE source IS NULL ORDER BY time) TO STDOUT WITH CSV HEADER" \
  > legacy_d015046_raw_taipower_load.csv
wc -l legacy_d015046_raw_taipower_load.csv
```

行數應等於第 3 節的 NULL 筆數加 1（標頭列）。請將檔案保存在版本控制之外。

---

## 5. 在交易中刪除並補上約束

開啟互動式 psql：

```bash
docker exec -it shiro_postgres psql -U postgres -d shiro_timeseries
```

依序執行：

```sql
BEGIN;
DELETE FROM raw_taipower_load WHERE source IS NULL;
```

確認 psql 回報的 `DELETE <n>` 與第 3 節的 NULL 筆數相同。相同時繼續：

```sql
ALTER TABLE raw_taipower_load ALTER COLUMN source SET NOT NULL;
COMMIT;
```

筆數不符時執行 `ROLLBACK;`，回到第 3 節重新盤點。

---

## 6. 驗證並啟用推算排程

1. 確認已無舊列且約束生效：

   ```bash
   docker exec shiro_postgres psql -U postgres -d shiro_timeseries -c \
     "SELECT COUNT(*) FILTER (WHERE source IS NULL) AS legacy_rows,
             (SELECT is_nullable FROM information_schema.columns
              WHERE table_name = 'raw_taipower_load' AND column_name = 'source') AS nullable
      FROM raw_taipower_load;"
   ```

   預期為 `legacy_rows = 0`、`nullable = NO`。
2. 開啟 `http://localhost:3000`，手動 materialize `raw_taipower_load` 一次，確認 run 成功。
3. 重跑第 3 節的查詢，確認只剩 `regional_snapshot_sum`。區域快照累積不足一小時時沒有新列，屬正常現象。
4. 在 Dagster UI 開啟 `hourly_actual_load_schedule`。
