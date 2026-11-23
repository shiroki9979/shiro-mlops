# ADR-0017：凍結基線 DDL，schema 遷移依序套用並留下紀錄

> - Created: 2026-11-23
> - Last Updated: 2026-11-23
> - Author: Bo-Xue Huang
> - Status: 已接受
> - Related: [ADR-0006](0006-timescaledb-local-storage-layer.md)、[ADR-0007](0007-isolate-cwa-access-behind-scheduled-ingestion.md)、[ADR-0008](0008-derive-hourly-actual-load-from-regional-snapshots.md)、[ADR-0009](0009-decouple-ml-tasks-via-task-config-and-task-types.md)、[資料模型與契約](../reference/data-contracts.md)

---

## 1. Context

地端時序資料庫的 schema 由一份 DDL（`src/shiro_mlops/core/sql/01_init_hypertables.sql`）定義，三處共用：Postgres 容器的 initdb、程式啟動時的 `ensure_timescale_hypertables`，以及測試用 SQLite 的轉換。既有資料庫另外經過四次對既有表的變更：隔離舊版氣象表（ADR-0007）、補上負載的 `source` 欄（ADR-0008）、`location` 改名為 `subject`（ADR-0009），以及移除 CWA header 的 `status` 欄。

這四次變更的做法相同：修改 DDL 讓它描述最新的 schema，再寫一個函式把舊資料庫改成同一個樣子。資料庫所在的版本沒有紀錄，每個函式在每次執行時檢視表與欄位，自行判斷是否已套用。這帶來三個問題：

- **每個遷移都要自行設計判斷方式**。能從 schema 看出來的變更（多一欄、少一欄）才寫得出來；只改資料或約束的變更沒有可靠的判斷依據。
- **多個 process 同時執行**。API 啟動時執行一次，每個用到資料庫的 Dagster run 也各執行一次。移除 `status` 欄時，後執行者在檢視之後、移除之前欄位已不存在而失敗，只能為該遷移個別補上 `DROP COLUMN IF EXISTS`。
- **版本無法查詢**。操作員只能從表與欄位反推資料庫經過了哪些變更。

initdb 掛載同一份 DDL，全新 volume 在程式啟動前就已建好所有表。因此「紀錄表不存在」分不出全新資料庫與紀錄表出現前的舊資料庫，任何依賴這個區別的設計都不可行。

## 2. Decision

DDL 凍結為**基線**，之後對既有表的變更一律寫成**遷移**；每筆遷移套用後在資料庫留下一列紀錄。

### 2.1 基線與遷移

- **基線凍結**：`01_init_hypertables.sql` 裡既有表的 `CREATE TABLE` 不再修改。新增整張表仍直接加進這份 DDL。
- **基線每次都執行**：`ensure_timescale_hypertables` 照舊先執行基線（全部是 `IF NOT EXISTS`），再套用遷移。
- **同一條路**：全新與既有資料庫都是「執行基線，然後依序套用紀錄表裡沒有的遷移」，不分辨資料庫的來歷。全新資料庫因此會實際執行每一筆遷移。
- **既有四筆遷移的銜接**：登記為 `0001` 至 `0004`，並保留各自的檢視邏輯。紀錄表出現前的資料庫沒有這四筆紀錄，第一次執行時各自檢視、已套用者不做事，然後寫入紀錄。`0005` 起的遷移不需要檢視邏輯。

### 2.2 紀錄表與遷移的形式

- **紀錄表** `schema_migration`（`id`、`applied_at`）由基線建立，不是 hypertable，不存 checksum。
- **遷移是 Python 函式**，放在 `src/shiro_mlops/core/schema_migrations.py` 的單一有序 tuple `MIGRATIONS`，TimescaleDB 與 SQLite 共用同一份順序。`id` 為四位序號加名稱，一經發布不得更改。
- **入口不變**：`ensure_timescale_hypertables(engine)` 仍是唯一會改 schema 的入口，簽章與語意不變。
- **查詢 interface 是紀錄表本身**：操作員以 `SELECT * FROM schema_migration ORDER BY id` 查詢，程式不提供讀取函式。

### 2.3 行為保證

- **兩態**：每筆遷移與它的紀錄列在同一個交易。失敗時兩者一起回滾、例外往外拋，下次執行重試。紀錄表不存「失敗」或「進行中」。
- **原子性只對 TimescaleDB 保證**：SQLite 執行 DDL 時即提交，只含 DDL 的遷移在 SQLite 上可能留下變更而沒有紀錄。SQLite 只用於測試。
- **同時執行**：TimescaleDB 上有未記錄的遷移時，在該遷移的交易內取 advisory lock，取得後重查紀錄表再決定是否執行。全部已記錄時只做一次查詢、不取鎖。SQLite 不加鎖。
- **不支援降版**：紀錄表出現程式不認得的 `id` 時拋出 `UnknownSchemaMigrationError`，API 啟動失敗，Dagster run 失敗。資料庫無法連線時 API 只記錄錯誤並照常啟動，這裡不能比照：資料庫連得上、資料也在，`/ready` 會回報就緒。

### Rationale & Alternatives Considered

- **選定方案：凍結基線，遷移依序套用並記錄**。新增遷移只需寫變更本身；同時執行由一把鎖統一處理；版本可以直接查詢。全新與既有資料庫走同一條路，遷移在每次建立測試資料庫時都被執行。
- **候選方案 A：引入 Alembic**。Alembic 的版本目錄會成為 schema 的第二個來源，而 initdb 與 SQLite 轉換仍需要那份 DDL，兩者必須人工保持一致。本專案的遷移少、只有單一地端部署，用不到分支合併、自動產生遷移與降版。
- **候選方案 B：DDL 維持最新，全新資料庫直接蓋章為最新版**。全新資料庫不必重跑歷史遷移，但需要分辨全新與既有資料庫才知道該蓋章還是該遷移。initdb 讓全新 volume 在程式啟動前就有表，分辨不出來；誤判為全新會跳過必要的遷移。每筆遷移也要在兩處表達同一件事（改 DDL 與寫遷移），遷移本身只在舊資料庫上執行，測試不到。
- **候選方案 C：維持現狀，每個遷移自行檢視**。已被上述三個問題否定；其中同時執行的失敗已經實際發生。
- **候選方案 D：紀錄表多存狀態或 checksum**。「進行中」與「失敗」需要另外的清理流程，而交易回滾已經讓這兩種狀態不存在。遷移是程式碼裡的函式，沒有可供比對的檔案內容，checksum 無從計算。

## 3. Consequences

- **正面效益（Positive）**：
  - 新增對既有表的變更時，只需在 `MIGRATIONS` 末尾加一筆，不必設計檢視邏輯，也不必個別處理同時執行。
  - 資料庫經過哪些變更、何時套用，可以直接查詢。
  - 只改資料或約束的變更也能表達為遷移（例如 [#358](https://github.com/shiroki9979/shiro-mlops/issues/358) 的 `SET NOT NULL`）。
- **代價與風險（Trade-offs & Risks）**：
  - 基線不再代表現行 schema。現行 schema 是基線加上全部遷移的結果，閱讀 DDL 時必須同時看 `MIGRATIONS`。
  - 以 DDL 當作現行 schema 的測試（例如 SQLite 與 TimescaleDB 的 schema 比對）在第五筆遷移出現時必須改為比對 `ensure_timescale_hypertables` 之後的結果。
  - 退回舊版程式會被拒絕啟動，只能還原資料庫備份或升回新版。
  - 直接以 SQL 手動修改 schema 不會留下紀錄，對應的遷移之後仍會執行。
  - 紀錄表出現前的程式版本不取鎖。新舊版本同時執行時，`0001` 至 `0004` 靠保留的檢視邏輯與 `IF EXISTS` 維持安全。
- **不做／延後範圍（Out of Scope / Deferred）**：
  - 需要操作員處理的資料狀態不在紀錄範圍內。負載表的 `source IS NULL` 舊列仍由全台逐時實際負載的累積盤點回報；升級後 `source` 仍可為 `NULL` 的缺口見 [#358](https://github.com/shiroki9979/shiro-mlops/issues/358)。
  - 基線裡 `raw_cwa_township_forecast` 的 `ADD COLUMN IF NOT EXISTS location_name` 維持原狀，不改寫為遷移。
  - 降版、遷移的 dry-run 與讀取紀錄的 Python 函式。

## 4. Compliance

- 單元測試（SQLite）：全新資料庫依序記錄全部 `id`，重跑不增不減；紀錄表出現前的各種舊樣貌升級後都被記錄；已記錄的遷移不再被呼叫；遷移失敗時不留紀錄並於下次重試；紀錄表有不認得的 `id` 時拋出 `UnknownSchemaMigrationError`，API 因此啟動失敗；已發布的 `id` 不得變動。
- TimescaleDB opt-in 驗收：兩個連線同時套用時遷移只執行一次；遷移中途失敗時 DDL 一併回滾；紀錄表不是 hypertable。
- Code Review 清單：不得修改基線裡既有表的 `CREATE TABLE`；不得更改或重新排序已發布的遷移 `id`；遷移函式不得自行開啟或提交交易；`0005` 起的遷移不寫檢視邏輯。

## 5. Notes

- 決策經 2026-11-23 的設計討論定案（[GitHub #296](https://github.com/shiroki9979/shiro-mlops/issues/296)），來源為 2026-11-22 的隱式狀態機盤點（[#284](https://github.com/shiroki9979/shiro-mlops/issues/284)）。
- 第四筆遷移（移除 CWA header 的 `status` 欄，[#339](https://github.com/shiroki9979/shiro-mlops/issues/339)）在設計定案的同一天合併，它的啟動競態由 [#291](https://github.com/shiroki9979/shiro-mlops/issues/291) 個別修正，是本決策處理的問題的實例。
