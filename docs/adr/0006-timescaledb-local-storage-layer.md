# ADR 0006: 地端引入 TimescaleDB 作為時序資料儲存庫與分層儲存架構

- 建立日期：2026-08-26
- 最後更新：2026-09-07
- 狀態：已接受 (Accepted)
- 關聯：[ADR-0001](0001-hybrid-topology-boundary.md)、[ADR-0002](0002-feast-storage-layer-strategy.md)、[ADR-0007](0007-isolate-cwa-access-behind-scheduled-ingestion.md)

---

## 脈絡 (Context)

在原先的架構設計中，台電與氣象時序資料直接以 Parquet 檔案形式儲存於本地與 S3。然而，在實際資料維運與即時資料接入情境下，面臨以下挑戰：

1. **資料回補與修正需求**：台電歷史負載資料偶有修正或延遲上報，Parquet 無法原地更新（In-place update），需全檔重寫。
2. **即時時序查詢與監控**：缺乏標準 SQL 與 Grafana 連線介面，無法直接對原始時序資料進行快速聚合、降採樣（Downsampling）與視覺化。
3. **雲地混合邊界維護**：需確保地端具備強大時序資料庫能力的同時，雲端仍維持零常駐資料庫費用的 Serverless 模式。

---

## 決策 (Decision)

採用 **「地端 TimescaleDB (Bronze/Silver) + Parquet/S3 (Gold/Feast Offline)」** 的雙層儲存架構：

1. **地端時序儲存庫 (TimescaleDB)**：
   - 將地端 Docker Compose 中的 PostgreSQL 映像檔升級為 TimescaleDB（`timescale/timescaledb:latest-pg15`）。
   - 建立 `taipower_load_raw` 與 `cwa_weather_raw` 之 Hypertables，支援 Upsert（`ON CONFLICT DO UPDATE`）與時間分區。
   - 兼作 MLflow Backend Store 與地端時序資料庫。
2. **Feast 與雲端特徵交換層 (Parquet on S3 / Local FS)**：
   - Dagster 排程管線自 TimescaleDB 讀取最新資料並計算特徵，定期導出為 Parquet 檔案（`data/taipower_features.parquet` 與 `s3://...`）。
   - Feast Offline Store 繼續以 Parquet 檔案配合 DuckDB/PyArrow 進行特徵檢索與時間旅行，確保雲端與地端特徵讀取一致且無常駐雲端 DB 成本。

---

## 取捨分析 (Trade-offs)

### 優點

- **高效資料回補與去重**：利用 TimescaleDB 的 Upsert 機制，安全處理台電歷史數據修正與重複上報。
- **豐富的時序 SQL 支援**：支援 `time_bucket` 與 Continuous Aggregates，大幅簡化時序降採樣與監控報表產出。
- **雲端成本零增加**：雲端依然維持 S3 + Serverless 拓撲，不需要在 AWS 部署 RDS TimescaleDB。
- **Feast 運算隔離**：Feast 的 Point-in-time join 由 DuckDB / Parquet 負擔，避免複雜 SQL 查詢癱瘓業務資料庫。

### 成本與風險

- **地端狀態維護**：地端 Docker Compose 需管理 TimescaleDB 的 Data Volume 與 Schema 遷移。
- **資料同步鏈路**：新增「TimescaleDB ➔ Parquet 導出」的 Dagster 資產轉換步驟。

### 適用情境

- 需兼顧地端高靈活性時序資料治理（回補、SQL 查詢、Grafana 監控）與雲端零常駐成本之混合 MLOps 架構。

---

## 合規與驗證 (Compliance)

1. 地端 `docker-compose.yml` 必須配置 TimescaleDB 容器並具備 Volume 持久化。
2. Dagster 必須具備自 TimescaleDB 寫入與讀取時序資產的測試案例。
3. Feast 離線定義維持 `FileSource` 指向 Parquet，不得直接硬編碼連線地端 DB 以免破壞雲端相容性。

---

## Notes

- 實作與 [SPEC.md](../SPEC.md) / init SQL 採用之 Hypertable 名稱為 `raw_taipower_load`、`raw_cwa_weather`（本 ADR Decision 段落中的 `taipower_load_raw` / `cwa_weather_raw` 為早期命名草圖，不以歷史改寫覆寫 Decision 本文）。
- CWA 外部 API 的排程式入庫與 consumer 隔離邊界由 [ADR-0007](0007-isolate-cwa-access-behind-scheduled-ingestion.md) 補充。
- 最後更新：2026-09-04（補充實作表名對照，不變更既有決策語意）。
- 最後更新：2026-09-07（新增 ADR-0007 關聯，不變更既有決策語意）。
