# ADR 0002: Feast 特徵庫之離線/線上儲存庫與註冊表配置策略

> - Created: 2026-08-23
> - Last Updated: 2026-11-27
> - Status: Accepted
> - Revisions: [Notes](#notes)

---

## Plain Language Summary

模型的輸入資料由特徵庫 Feast 管理，它需要三種儲存：離線資料、線上快速查詢，以及記錄資料定義的登記檔。全部採用雲端託管的資料庫服務，每月都有固定費用；全部放在單機，雲端的服務又讀不到。因此決定離線資料與登記檔都存成檔案，放在本機或 S3，線上查詢則用本機容器裡的 Redis。代價是檔案式的儲存只適合數百萬筆以內的資料，資料量再大就得搬到專門的分析平台。這個決定目前只適用於動態長度的負載預報這一項工作（見 [ADR-0009](0009-decouple-ml-tasks-via-task-config-and-task-types.md)）。

---

## 脈絡 (Context)

Feature Store (Feast) 需要分別定義 Offline Store（用於離線特徵抽取與時間旅行）、Online Store（用於線上隨需推論低延遲特徵查詢）與 Registry（特徵定義元數據）。在混合雲地架構下，若全面採用雲端全託管服務（如 AWS ElastiCache, Redshift）將產生高昂常駐月費；若純本機運行則無法支援雲端推論服務。

---

## 決策 (Decision)

1. **Registry**：
   - 採用 **S3 Bucket (`s3://.../registry.pb`)** 或本地檔案。維持單一真相來源，地端 Worker 與雲端 API 皆指向同一個 Registry 檔案。
2. **Offline Store**：
   - 採用 **Parquet File Source on S3 / Local FS**。由 Dagster 產生 Parquet 檔案，Feast 透過 DuckDB/PyArrow 直接查詢，零常駐資料庫成本。
3. **Online Store**：
   - 地端開發與測試：使用 **Docker Compose Redis**（`localhost:6379`）。
   - 雲端推論備援：透過 S3 Snapshot 進行冷啟動快取載入。

---

## 取捨分析 (Trade-offs)

### 優點

- **零資料庫長時帳單**：Parquet on S3 僅依儲存容量計費，完全免除 Redshift/Snowflake/RDS 的常駐基礎費用。
- **純地端環境對齊**：地端 Docker Redis 能精確模擬高並發低延遲特徵查詢，直接對齊企業地端機房之 MLOps 實務。

### 成本與風險

- **大規模分析擴展限制**：Parquet + FileSource 適合中小規模（數百萬筆以內）時序資料，若未來資料量增至數十億筆，需遷移至 BigQuery 或 Spark/Glue。

### 適用情境

- 輕量化時序/表格特徵工程、講求低維運成本與可攜性的混合雲平台。

---

## Notes

- 2026-09-27：[ADR-0009](0009-decouple-ml-tasks-via-task-config-and-task-types.md) 將 Feast 凍結為動態視界預報任務專屬的匯出，不納入 ML 任務抽象；本決策適用範圍縮為該任務，決策內容不變。
