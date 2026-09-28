# 專案發展藍圖與任務清單 (ROADMAP.md)

- 建立日期：2026-08-23
- 最後更新：2026-09-28
- 專案版本：`0.4.0`

本文檔定義 `shiro-mlops` 的階段性里程碑（Milestones）與各項 Tracer-Bullet 工單，每個工單皆為具備獨立完成標準（Definition of Done, DoD）的垂直切片。

---

## 里程碑總覽 (Milestone Overview)

| 里程碑 | 目標 | 主要模組 | 驗證標準 |
| :--- | :--- | :--- | :--- |
| **M1: 視覺化儀表板** | 實作 React 19 SPA 現代化儀表板，對接 FastAPI 隨需預測 | `frontend/` | 成功啟動並通過 Vitest 測試與 Vite 生產打包建置 (已完成) |
| **M2: 上游中斷韌性與降級預報** | CWA 擷取指數退避重試，serving 依常模降級並拒絕過舊負載起點 | `src/shiro_mlops/pipelines/`, `src/shiro_mlops/service/` | CWA 擷取中斷時以 `mode: "degraded"` 產出預報；負載起點過舊時回傳 HTTP 503 |
| **M3: 多測站與行事曆特徵** | 納入全台三區測站溫度加權與台灣節假日特徵 | `src/shiro_mlops/features/` | 特徵矩陣擴充且單元測試通過，MAPE 指標提升 |
| **M4: 雲端部署與 CI/CD** | Terraform 基礎設施部署、GitHub Rulesets 與 CI/CD 串接 | `infra/terraform/`, `.github/` | PR Merge 自動建置 ECR 映像檔，主分支與標籤保護生效 |
| **M5: 營運資料檢視器** | 建立地端唯讀 Data Explorer，檢查電力與氣象入庫資料 | `src/shiro_mlops/data/`, `src/shiro_mlops/service/`, `frontend/` | 六個 typed datasets 與 CWA audits 可依領域條件分頁檢視，狀態判讀與自動化測試通過 (已完成) |
| **M6: 全台逐時實際負載重建** | 由區域供需快照推算逐時負載，恢復訓練與 drift 排程（優先於 M3） | `src/shiro_mlops/pipelines/`, `src/shiro_mlops/data/` | `raw_taipower_load` 每小時產出推算值，累積滿 28 日後訓練排程可正常執行 |
| **M7: ML 任務解耦** | 以任務設定與任務類型解耦單一負載任務，並以高負載預警、用電型態異常偵測驗證（優先於 M3） | `src/shiro_mlops/`, `tasks/` | 三個 ML 任務皆由任務設定產生資產與排程，並經 `POST /tasks/{task_id}/predict` 提供推論 |

---

## 架構改善評估

[2026-09-27 架構檢視紀錄](explanation/2026-09-27-architecture-review.md) 保存三項架構改善候選：
集中營運資料檢視器分頁規則、集中預報版本選取與降級解析，以及收攏營運資料檢視器查詢生命週期。
分頁規則已完成 Q1 至 Q8 的設計討論，並依 [GitHub #72](https://github.com/shiroki9979/shiro-mlops/issues/72) 實作 v2 cursor、精確閉區間與八資料集共用查詢路徑。
五張工單已確認並發布為 [#73](https://github.com/shiroki9979/shiro-mlops/issues/73)、[#74](https://github.com/shiroki9979/shiro-mlops/issues/74)、[#75](https://github.com/shiroki9979/shiro-mlops/issues/75)、[#76](https://github.com/shiroki9979/shiro-mlops/issues/76)、[#77](https://github.com/shiroki9979/shiro-mlops/issues/77)，依序為共用流程與觀測批次、預報、逐時資料、供需與機組、精確窗口及舊流程退場。
實作順序為 #73 → #74／#75／#76 → #77；SQLite 與隔離本機 TimescaleDB 驗收方式見 [操作文件](how-to/verify-data-explorer-pagination.md)。其餘兩項候選維持待評估，證據與取捨詳見架構檢視紀錄。

---

## 詳細工單規格 (Tracer-Bullet Tickets)

### Milestone 1: 視覺化儀表板實作 (Frontend Dashboard)

#### [TICKET-101] 建立 React 19 + Vite + TanStack 現代化 SPA 儀表板

- **目標**：建立生產級 React 19 + TypeScript + Vite + TanStack Router/Query 單頁應用程式。
- **功能範圍**：
  1. 4 大頁面導航：即時預測總覽 (`/`)、歷史回測 (`/history`)、資料漂移監控 (`/monitoring`)、系統設定 (`/settings`)。
  2. 負載與氣候走勢圖：Recharts 繪製 1~72h 負載（MW）與氣溫（°C）雙 Y 軸互動走勢圖。
  3. 關鍵指標與明細：最高尖峰用電預估卡、逐時明細表與 CSV 資料匯出。
  4. 系統健康指標：對接 `/health` 顯示 API 版本、環境與模型載入狀態，支援 MSW 離線測試。
- **完成標準 (DoD)**：
  - 建立 `frontend/` 完整 SPA 架構與測試環境。
  - 執行 `pnpm run test` 全數通過（Vitest + MSW v2 離線測試）。
  - 執行 `pnpm run build`（`tsc -b && vite build`）與 `pnpm run lint` 無報錯。

---

### Milestone 2: 上游中斷韌性與降級預報 (Upstream Resiliency)

> 依 [ADR-0007](adr/0007-isolate-cwa-access-behind-scheduled-ingestion.md)，serving 只讀 TimescaleDB，不為 data clients 新增本地快取；台電負載來源移至 M6。

#### [TICKET-201] CWA 擷取韌性與負載起點過舊防護 ([GitHub #62](https://github.com/shiroki9979/shiro-mlops/issues/62))

- **目標**：上游擷取中斷時，serving 依常模降級並明確揭露；負載起點過舊時拒絕預報。
- **功能範圍**：
  1. CWA 觀測與預報 ingestion jobs 改為 `max_retries=3, delay=30` 指數退避重試。
  2. 新增負載起點過舊判斷（`LOAD_ANCHOR_MAX_LAG_HOURS`，預設 3 小時），`/ready` 與 `/predict` 回傳 HTTP 503。
  3. 維持 `status: "success"` 與 `mode: "normal" | "degraded"` 分離語意。
- **完成標準 (DoD)**：
  - 新增 `tests/integration/test_resiliency.py`，離線涵蓋 CWA HTTP 500、預報過期降級、替代資料皆缺、負載起點過舊與 serving 不建立 `CWAClient` 五個情境。

---

### Milestone 3: 多測站與節假日特徵工程深化

> 依 [ADR-0009](adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md)，於 M7 完成後以任務設定（氣象代表點權重、日曆特徵開關）實作。

#### [TICKET-301] 擴充全台三區測站溫度加權與行事曆特徵

- **目標**：提高預測精度，反映北中南用電重鎮氣候差異。
- **功能範圍**：
  1. CWA 抓取臺北 (466920)、臺中 (467490)、高雄 (467441) 測站氣溫；高雄使用 2022 年遷站後的現行站號。
  2. 計算人口/用電加權平均溫度：$T_{weighted} = 0.45 \cdot T_{north} + 0.30 \cdot T_{central} + 0.25 \cdot T_{south}$。
  3. 整合台灣國定假日套件（如 `holidays`），加入 `is_holiday` 特徵。
- **完成標準 (DoD)**：
  - `tests/unit/test_transformers.py` 通過多測站特徵轉換測試。

---

### Milestone 4: 雲端部署與 CI/CD 實測

#### [TICKET-401] Terraform 雲端佈署驗證與 GitHub Actions 整合

- **目標**：驗證 AWS 資源宣告與 CI 映像檔發布。
- **功能範圍**：
  1. 執行 `terraform validate` 與 `terraform plan` 本地檢查。
  2. 設定 GitHub Actions workflow 在 push to `main` 時自動打包 Docker 映像檔。
- **完成標準 (DoD)**：
  - CI workflow 包含 Terraform 格式檢查與 Docker 建置階段。

#### [TICKET-402] 建立 GitHub Rulesets 分支與標籤保護機制

- **目標**：透過 GitHub Rulesets 建立主分支與發布標籤之保護策略，落實程式碼品質門禁與合規性審計。
- **功能範圍**：
  1. 建立 `main` 分支保護 Ruleset：
     - 要求 Pull Request 合併前必須通過 CI 檢查（pytest 測試、Ruff lint/format）。
     - 要求至少 1 位審查者核准 (Code Review approval)。
     - 禁止強制推送（Force Push）與刪除分支。
     - 要求線性提交歷史（Linear History）。
  2. 建立 Release Tags (`v*`) 保護 Ruleset：
     - 防止任意覆蓋或刪除已發布標籤。
  3. 配置 Push Ruleset（大檔與敏感檔案防護）：
     - 限制超出上限之大檔與未經授權副檔名推送。
  4. 產出 Ruleset 配置規範與匯出檔（JSON），納入儲存庫維護手冊。
- **完成標準 (DoD)**：
  - 完成 GitHub Rulesets 設定，`main` 分支受 PR 與 CI 門禁保護。
  - 新增或更新相關治理文件，記錄 Rulesets 規範與 bypass 例外清單。

---

### Milestone 5: 營運資料檢視器 (Data Explorer) ([GitHub #40](https://github.com/shiroki9979/shiro-mlops/issues/40))

#### [TICKET-501] 建立共用查詢契約與逐時負載 Explorer ([GitHub #41](https://github.com/shiroki9979/shiro-mlops/issues/41))

- **目標**：以第一個完整垂直切片建立 dataset status、cursor pagination 與 Data Explorer 共用介面。
- **完成標準 (DoD)**：逐時負載可在有界時間內篩選、分頁、檢視 typed detail 與匯出當頁 CSV；status 及 API／frontend 契約測試通過。

#### [TICKET-502] 加入全台供需 Explorer ([GitHub #44](https://github.com/shiroki9979/shiro-mlops/issues/44))

- **目標**：提供全台供需快照的唯讀營運檢視。
- **完成標準 (DoD)**：可在七日有界時間內查詢、分頁、檢視 MW／萬瓩與全部 typed fields，並揭露可用性、新鮮度與完整度。

#### [TICKET-503] 加入區域供需 Explorer ([GitHub #45](https://github.com/shiroki9979/shiro-mlops/issues/45))

- **目標**：提供北、中、南、東四區發電與用電快照的唯讀營運檢視。
- **完成標準 (DoD)**：可依時間、region 與完整度篩選，正確判定每個 slot 是否具備四區，並顯示 MW／萬瓩與 typed detail。

#### [TICKET-504] 加入機組發電 Explorer ([GitHub #46](https://github.com/shiroki9979/shiro-mlops/issues/46))

- **目標**：提供高筆數機組發電快照的唯讀營運檢視。
- **完成標準 (DoD)**：可依時間、unit type 與 unit name 篩選及 keyset 分頁，正確呈現 nullable typed fields，且不以固定機組數量判定不完整。

#### [TICKET-505] 加入 CWA 測站觀測 Explorer ([GitHub #42](https://github.com/shiroki9979/shiro-mlops/issues/42))

- **目標**：提供 canonical CWA 測站觀測與逐時缺口的唯讀營運檢視。
- **完成標準 (DoD)**：可依時間與 station 篩選、分頁與檢視 typed fields，並分開顯示 ingestion age、source age 與逐時缺口。

#### [TICKET-506] 加入 CWA Observation Audit History ([GitHub #47](https://github.com/shiroki9979/shiro-mlops/issues/47))

- **目標**：追查 CWA observation batch 的完整與不完整歷史。
- **完成標準 (DoD)**：可依時間、status 與 missing station identifier 篩選及分頁，可從測站觀測頁 deep-link，且不回傳 raw payload。

#### [TICKET-507] 加入 CWA 鄉鎮預報 Explorer ([GitHub #43](https://github.com/shiroki9979/shiro-mlops/issues/43))

- **目標**：提供 canonical CWA 鄉鎮預報所有已保存 vintages 的唯讀營運檢視。
- **完成標準 (DoD)**：預設顯示最新發布版本，並可依有效時間、dataset、geocode、issued/updated version 篩選、分頁與檢視 typed fields。

#### [TICKET-508] 加入 CWA Forecast Audit History ([GitHub #48](https://github.com/shiroki9979/shiro-mlops/issues/48))

- **目標**：追查 CWA forecast release 的版本、完整與不完整歷史。
- **完成標準 (DoD)**：可依時間、dataset、status 與 missing geocode 篩選及分頁，可從鄉鎮預報頁 deep-link，且不回傳 raw payload。

#### [TICKET-509] 整合 Monitoring Data Source Status ([GitHub #49](https://github.com/shiroki9979/shiro-mlops/issues/49))

- **目標**：讓 Monitoring 使用共用 dataset status 顯示所有資料來源的營運狀態。
- **完成標準 (DoD)**：Monitoring 顯示 availability、freshness 與 completeness，並 deep-link 至對應 Explorer；舊 Feature Store Snapshot 在過渡期間繼續可用。

#### [TICKET-510] 退場舊 Feature Store Snapshot Contract ([GitHub #50](https://github.com/shiroki9979/shiro-mlops/issues/50))

- **目標**：在 Data Explorer 完整可用後移除實際未查詢 Feast 的誤標快照路徑。
- **完成標準 (DoD)**：舊 Feature Store Snapshot、`/features/latest`、相關 schema、mock、文件與測試已移除，Monitoring 只保留新 Data Source Status。

---

### Milestone 6: 全台逐時實際負載重建 (Hourly Actual Load Recovery)

> 依 [ADR-0008](adr/0008-derive-hourly-actual-load-from-regional-snapshots.md)，放棄尋找可回補的官方歷史來源（[GitHub #58](https://github.com/shiroki9979/shiro-mlops/issues/58) not planned）；此里程碑為 M3 MAPE 驗收的前置條件。

#### [TICKET-601] 由區域快照推算全台逐時實際負載 ([GitHub #59](https://github.com/shiroki9979/shiro-mlops/issues/59))

- **目標**：以區域供需快照四區加總的小時平均取代已失效的 d015046，恢復 `raw_taipower_load`。
- **完成標準 (DoD)**：`hourly_actual_load_job` 冪等產出符合有效樣本與 4／6 完整度門檻的逐時值；區域快照改為指數退避重試；d015046 路徑與舊資料列已移除；推算規則離線測試通過。

#### [TICKET-602] 恢復排程式訓練與 drift ([GitHub #60](https://github.com/shiroki9979/shiro-mlops/issues/60))

- **目標**：負載入庫恢復後，每日訓練與每小時 drift 回到可操作驗證狀態。
- **完成標準 (DoD)**：排程不再固定暫停；有效逐時觀測少於 672 小時時訓練明確拒絕；container smoke check 與操作文件完成。

---

### Milestone 7: ML 任務解耦 (ML Task Decoupling) ([GitHub #64](https://github.com/shiroki9979/shiro-mlops/issues/64))

> 依 [ADR-0009](adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md) 與 [ADR-0010](adr/0010-persist-models-in-native-non-executable-formats.md)；M6 累積 28 日期間進行，完成後接續 M3。

#### [TICKET-701] 拆分預測對象與氣象代表點 ([GitHub #65](https://github.com/shiroki9979/shiro-mlops/issues/65))

- **目標**：全台逐時實際負載的預測對象由 `Taipei` 遷移為 `nationwide`，天氣改以氣象代表點取得。
- **完成標準 (DoD)**：`raw_taipower_load` 以 `subject` 識別且遷移可重複執行；測站與鄉鎮代碼只存在於擷取目錄；`/predict` 的 `location` 標示 deprecated 並回傳 `subject`；Data Explorer 與前端配合調整。

#### [TICKET-702] 建立任務設定與任務類型，搬入動態視界預報 ([GitHub #66](https://github.com/shiroki9979/shiro-mlops/issues/66))

- **目標**：以 `tasks/<task_id>.toml` 與任務類型 registry 描述現行任務，對外行為不變；模型改存 LightGBM 原生文字格式。
- **完成標準 (DoD)**：任務設定載入錯誤於啟動時失敗；特徵配方單一來源；`src/` 不 import `joblib`／`pickle`；對外行為測試除識別碼與模型格式外不修改斷言，內部模組測試改寫至新介面。

#### [TICKET-703] 以資產工廠產生每任務 Dagster 資產與 MLflow experiment ([GitHub #67](https://github.com/shiroki9979/shiro-mlops/issues/67))

- **目標**：由任務設定產生 `{task_id}__*` 資產、排程與監控規則，擷取資產跨任務共用。
- **完成標準 (DoD)**：新增一份任務設定即產生對應資產與排程；每任務獨立 MLflow experiment 與模型目錄；健康判定門檻來自任務設定。

#### [TICKET-704] 通用推論端點 ([GitHub #68](https://github.com/shiroki9979/shiro-mlops/issues/68))

- **目標**：提供 `POST /tasks/{task_id}/predict` 與 `GET /tasks/{task_id}/ready`，`/predict`、`/ready` 保留為動態視界預報別名。
- **完成標準 (DoD)**：未知任務回 404；單一任務模型缺失不影響其他任務；別名與通用端點結果一致。

#### [TICKET-705] 高負載預警任務 ([GitHub #69](https://github.com/shiroki9979/shiro-mlops/issues/69))

- **目標**：以直接策略 `LGBMClassifier` 判定未來各小時是否超過高負載門檻（錨點前 28 日 P90）。
- **完成標準 (DoD)**：門檻計算無未來資料洩漏；precision、recall、F1 記錄於 MLflow；端點回傳 `is_high_load`、`probability`、`threshold_mw`。

#### [TICKET-706] 用電型態異常偵測任務 ([GitHub #70](https://github.com/shiroki9979/shiro-mlops/issues/70))

- **目標**：以淺層 MLP AutoEncoder 對 24 小時滑動窗評分，偵測用電型態異常。
- **完成標準 (DoD)**：numpy 前向計算與 sklearn 輸出一致；合成異常注入的召回率與誤報率記錄於 MLflow；不新增相依。
