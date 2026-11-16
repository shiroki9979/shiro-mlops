# ADR-0008：由區域供需快照推算全台逐時實際負載

> - Created: 2026-09-26
> - Last Updated: 2026-11-16
> - Author: Bo-Xue Huang
> - Status: 已接受
> - Related: [ADR-0004](0004-dagster-asset-based-orchestration.md)、[ADR-0006](0006-timescaledb-local-storage-layer.md)、[ADR-0007](0007-isolate-cwa-access-behind-scheduled-ingestion.md)、[台電逐時負載來源調查](../research/2026-09-16-taipower-hourly-actual-load-source.md)、[Issue #58](https://github.com/shiroki9979/shiro-mlops/issues/58)、[Issue #59](https://github.com/shiroki9979/shiro-mlops/issues/59)

---

## 1. Context

模型目標與遞迴預測起點都依賴全台逐時實際負載，但原本設定的 d015046 已失效，且只提供每日尖峰。2026-09-16 的調查未找到具來源時間、全台口徑、逐時粒度且可重抓的官方歷史端點；每日尖峰（d006005）、機組淨發電量與區域潮流皆口徑不符。訓練與 drift 排程因此暫停，系統沒有可信任的負載序列。

同時，`raw_taipower_regional_supply_demand_snapshot` 已每十分鐘保存 d006019 四區用電與來源 `時間`。調查實測四區加總與 d006020 `curr_load` 僅差 0.1 萬瓩（顯示值四捨五入），可作為全台負載的衍生觀測。

## 2. Decision

放棄尋找可回補的官方歷史來源。以區域供需快照推算**全台逐時實際負載**，作為 `raw_taipower_load` 的唯一來源：

- **有效樣本**：以 `source_time` 識別樣本，重複擷取只計一次；四區齊全且 `source_time` 相同才有效；四區 `load_wan_kw` 加總後乘以 10 轉為 MW。
- **逐時聚合**：取 `[HH:00, HH+1:00)`（`Asia/Taipei`）內有效樣本的平均，標記於小時起點 `HH:00`；有效樣本少於門檻（預設 4／6）時該小時為缺值，不內插；未結束的小時不產出。
- **產生方式**：每小時 Dagster asset 重算最近數小時並 upsert，以吸收重試成功但較晚寫入的樣本；每列標記推算來源。
- **邊界修訂**：區域快照可作為本推算的輸入，但仍不得直接作為模型特徵；全台供需快照與機組快照維持原邊界。
- **最低累積**：有效逐時觀測少於 28 日（672 小時，設定值）時不得訓練。

### Implementation Refinements

實作期間（[Issue #60](https://github.com/shiroki9979/shiro-mlops/issues/60)、[Issue #62](https://github.com/shiroki9979/shiro-mlops/issues/62)）細化的契約：

- **既有資料庫升級**：新建資料庫的 `raw_taipower_load.source` 為 NOT NULL；既有資料庫升級時只補上 nullable `source`，不改寫既有列，以 NULL 標示 d015046 時期舊列。操作人員依 [d015046 舊列清除指南](../how-to/remove-legacy-d015046-load-rows.md) 審閱並刪除舊列後，再將欄位設為 NOT NULL。
- **舊列存在時的行為**：只要仍有 `source IS NULL` 的列，訓練就緒即判定為未就緒（排程略過、手動執行失敗）；serving 與 drift 只讀 `source = 'regional_snapshot_sum'` 的列，舊列不得成為遞迴起點或歷史輸入。
- **drift 觸發**：`hourly_drift_schedule` 除最低累積外，另需 `trained_forecaster_model` 已有 materialization；drift 只以有界查詢讀取有效時數與最新一列，不重讀整段歷史。
- **CWA 預報 stale 判定**：serving 以請求時間作為 `as_of`，只採用請求當下已發布且已更新的預報版本，並以請求時間判定最新發布是否超過七小時。

### Rationale & Alternatives Considered

- **選定方案：區域快照四區加總後取小時平均**。來源為官方且帶來源時間，已在排程累積；平均值對單一取樣抖動與偶發漏抓較穩健。
- **候選方案 A：d006020 `curr_load`**。口徑相同但沒有來源時間欄，不能補造 timestamp；僅保留為監測對照。
- **候選方案 B：整點瞬時值**。語意直觀，但整點樣本一次漏抓就失去整個小時。
- **候選方案 C：d006005 每日尖峰降採樣或內插成逐時**。會捏造頻率，拒絕。
- **候選方案 D：維持無來源狀態等待台電發布歷史資料**。沒有可預期的時程，專案無法訓練或驗證任何後續特徵工作。

## 3. Consequences

- **正面效益（Positive）**：恢復可信任的負載目標與遞迴起點；下游 `raw_taipower_load` 契約不變；每個逐時值可追溯至區域快照來源時間。
- **代價與風險（Trade-offs & Risks）**：
  - 序列只能自累積起往後取得，無法回補；累積滿 28 日前不能訓練。
  - 季節性（夏季冷氣尖峰）需累積滿一年才完整，初期模型對跨季變化不可靠。
  - 區域快照成為負載的單點來源，錯過的快照永久缺失；擷取重試因此加強，但無法消除長時間中斷造成的缺口。
  - 區域用電依跨區潮流調整，本推算是本系統定義的衍生觀測，不等同台電官方公布的系統負載。
- **不做／延後範圍（Out of Scope / Deferred）**：不回補歷史；不以內插填補缺值；若日後台電提供合格官方逐時歷史來源，另以新 ADR 評估取代或校正。

## 4. Compliance

- 推算測試必須覆蓋：四區不齊或 `source_time` 不一致的樣本被排除、重複 `source_time` 只計一次、樣本數低於門檻的小時不產出、未結束小時不產出、重算冪等。
- 訓練與 drift 資產不得讀取任何快照表；只能經由 `raw_taipower_load` 取得負載。
- 啟用推算前須確認並清除 `raw_taipower_load` 中 d015046 時期的資料列，避免不同口徑混用；清除前訓練維持未就緒，serving 與 drift 以 `source` 篩選忽略舊列。

## 5. Notes

- 2026-11-16 一次性重算：排程推算只重算最近幾小時，因此推算上線前（2026-09-06 起）已入庫的區域快照，以及擷取中斷邊界上已達樣本門檻的小時（`2026-10-30 23:00`、`2026-11-09 02:00`），從未產出逐時負載。以 `scripts/rederive_hourly_actual_load.py` 對這些**已入庫**的快照套用相同推算規則補出 379 小時。
  - 這不屬於「回補」：不向台電重抓任何資料，只處理本系統已擷取的快照；推算規則與排程相同，且只寫入尚無資料的小時，不覆寫既有列。
  - 執行前查核：2026-09-28 前後的快照單位（萬瓩）、取樣頻率（每 10 分鐘）一致；以同一規則重算既有 854 小時，與已存值的最大差為 7e-12 MW。
  - 動機為滾動起點回測需要足夠的評估起點（[#98](https://github.com/shiroki9979/shiro-mlops/issues/98)）；排程推算的時窗缺陷另見 [#113](https://github.com/shiroki9979/shiro-mlops/issues/113)。
