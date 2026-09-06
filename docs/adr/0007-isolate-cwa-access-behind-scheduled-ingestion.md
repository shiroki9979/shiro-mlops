# ADR-0007：將 CWA 外部存取隔離於排程式入庫邊界

> - Created: 2026-09-07
> - Last Updated: 2026-09-07
> - Author: White Hunag
> - Status: 提議中
> - Related: [ADR-0006](0006-timescaledb-local-storage-layer.md)、[Issue #30](https://github.com/shiroki9979/shiro-mlops/issues/30)

---

## 1. Context

訓練與線上推論目前各自直接呼叫 CWA API，造成外部延遲、重試、解析版本與資料完整度分散在多個執行路徑，也無法重現某次預測當時實際可得的預報版本。系統需要在即時性、可重現性與服務可用性之間建立單一且可驗證的整合邊界。

## 2. Decision

CWA 外部 API 只允許由彼此獨立的 Dagster 測站觀測與鄉鎮預報 ingestion jobs 呼叫。jobs 將完整來源回應與 canonical typed records 寫入 TimescaleDB；訓練、drift 與 FastAPI serving 只讀 canonical tables，不得在資料缺少時繞過入庫邊界直接呼叫 CWA。

測站觀測以來源 `ObsTime` 與 `StationId` 識別；鄉鎮預報以資料集、`IssueTime`、`Update`、有效區間及 `Geocode` 保存所有版本。Serving 優先使用資料庫中的最新合格預報，過期或缺少時依明確常模策略降級，並透過 readiness 與 per-field provenance 揭露狀態。

### Rationale & Alternatives Considered

- **選定方案：排程入庫是唯一外部整合邊界**。集中授權碼、重試、資料品質與版本治理，提供穩定 serving latency 及 point-in-time correct 的回測來源。
- **候選方案 A：consumer 優先讀資料庫、缺少時 live fallback**。可縮短短暫資料缺口，但會重新引入多重擷取路徑，讓線上結果依外部網路狀態而變動。
- **候選方案 B：consumer 持續直接呼叫 CWA，入庫只作稽核**。改動較少，但無法保證訓練與 serving 使用相同版本，也無法隔離 CWA 故障與延遲。

## 3. Consequences

- **正面效益（Positive）**：CWA 解析與資料品質規則只有一份；預報版本可重現；FastAPI 不承受 CWA 網路延遲；排程失敗與 incomplete 批次可獨立監控。
- **代價與風險（Trade-offs & Risks）**：TimescaleDB 與 Dagster 成為預測前置相依；空資料庫需先完成 ingestion 與訓練；排程中斷可能使預報進入降級模式。
- **不做／延後範圍（Out of Scope / Deferred）**：三站加權特徵仍由 TICKET-301 處理；本決策不改變台電資料的外部存取邊界。

## 4. Compliance

- 離線測試必須驗證訓練與 FastAPI 路徑不建立或呼叫 `CWAClient`。
- repository 測試必須覆蓋 observation upsert、forecast-vintage 並存、incomplete batch 與 point-in-time 查詢。
- Dagster 測試必須驗證兩個 CWA jobs、錯峰 schedules、有限重試及其與訓練／台電 jobs 的選取隔離。
- API 測試必須覆蓋 `/ready` 的 200／503、正常／降級模式，以及逐欄天氣來源 provenance。
- `CWA_API_KEY` 只能由執行環境注入，不得寫入程式碼、fixture、文件範例值或資料庫。

## 5. Notes

- 本 ADR 補充 [ADR-0006](0006-timescaledb-local-storage-layer.md) 的 CWA 外部整合與消費邊界，不取代其 TimescaleDB／Parquet 分層決策。
- Issue #30 原本只涵蓋 CWA API key wiring；本次設計確認後將擴大為完整 CWA 本機 ingestion 垂直切片。
- 實作與遷移尚未開始；待 grilling 共識確認後進行。
