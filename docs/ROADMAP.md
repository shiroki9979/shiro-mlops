# 專案發展藍圖與任務清單 (ROADMAP.md)

- 建立日期：2026-08-23
- 最後更新：2026-11-20
- 專案版本：`0.4.0`

本文檔定義 `shiro-mlops` 的階段性里程碑（Milestones）與各項 Tracer-Bullet 工單，每個工單皆為具備獨立完成標準（Definition of Done, DoD）的垂直切片。以下狀態依儲存庫程式碼、已合併 PR 與 GitHub issue 核對；需要正式資料或雲端設定的驗收另行標示，不以 issue 關閉代替現場驗證。

---

## 里程碑總覽 (Milestone Overview)

| 里程碑 | 狀態 | 目標 | 主要模組 | 驗證標準 |
| :--- | :--- | :--- | :--- | :--- |
| **M1: 視覺化儀表板** | 功能已完成；部署未納入 | 實作 React 19 SPA 現代化儀表板，對接 FastAPI 隨需預測 | `frontend/` | 成功啟動並通過 Vitest 測試與 Vite 生產打包建置 |
| **M2: 上游中斷韌性與降級預報** | 已完成 | CWA 擷取指數退避重試，serving 依常模降級並拒絕過舊負載起點 | `src/shiro_mlops/pipelines/`, `src/shiro_mlops/service/` | CWA 擷取中斷時以 `mode: "degraded"` 產出預報；負載起點過舊時回傳 HTTP 503 |
| **M3: 加權天氣與放假日特徵** | 能力已完成；採用待研究 | 以全台三區氣象代表點的加權天氣與放假日特徵改善動態視界預報 | `src/shiro_mlops/tasks/`, `src/shiro_mlops/features/`, `src/shiro_mlops/data/`, `lab/` | 能力：多代表點與放假日的離線測試通過；採用：lab 滾動起點回測在至少 7 個評估日贏過基線後修改任務設定 |
| **M4: 雲端部署與 CI/CD** | 部分完成 | 以 S3 + CloudFront 公開預先算好的預報檢視、Terraform 基礎設施、GitHub Rulesets 與 CI/CD 串接 | `infra/terraform/`, `.github/`, `frontend/`, `src/shiro_mlops/pipelines/` | release 合併後自動建置並部署預報檢視，雲端顯示地端匯出的最新已發布預報與預報實績；主分支與標籤保護生效 |
| **M5: 營運資料檢視器** | 已完成 | 建立地端唯讀 Data Explorer，檢查電力與氣象入庫資料 | `src/shiro_mlops/data/`, `src/shiro_mlops/service/`, `frontend/` | 六個 typed datasets 與 CWA audits 可依領域條件分頁檢視，狀態判讀與自動化測試通過 |
| **M6: 全台逐時實際負載重建** | 程式已交付；營運待驗收 | 由區域供需快照推算逐時負載，恢復訓練與 drift 排程（優先於 M3） | `src/shiro_mlops/pipelines/`, `src/shiro_mlops/data/` | `raw_taipower_load` 每小時產出推算值，有效逐時觀測達 672 小時（連續無缺漏時約 28 日）後 `dynamic_horizon_forecast` 訓練排程可正常執行 |
| **M7: ML 任務解耦** | 程式已完成；模型可用性待驗證 | 以任務設定與任務類型解耦單一負載任務，並以高負載預警、用電型態異常偵測驗證（優先於 M3） | `src/shiro_mlops/`, `src/shiro_mlops/tasks/` | 三個 ML 任務皆由任務設定產生資產與排程，並經 `POST /tasks/{task_id}/predict` 提供推論 |
| **M8: 研究空間 (Lab)** | 實作中 | 建立同庫單向相依的 `lab/` 研究空間、訓練表快照、滾動起點回測與超參數研究流程 | `lab/`, `src/shiro_mlops/tasks/` | 快照無損往返、滾動起點回測與基線／Optuna 研究報告可重現，且 `uv run --package lab pytest lab/tests` 通過 |

M2、M6、M7 的實作已隨 [PR #79](https://github.com/shiroki9979/shiro-mlops/pull/79) 合併至 `main`；M5 已隨 [PR #56](https://github.com/shiroki9979/shiro-mlops/pull/56) 合併，分頁規則後續由 [PR #78](https://github.com/shiroki9979/shiro-mlops/pull/78) 完成。M6 與 M7 的正式資料累積、首次訓練及模型就緒仍需依[冷啟動驗收指南](how-to/recover-training-after-load-cold-start.md)於運行環境確認。

[#81](https://github.com/shiroki9979/shiro-mlops/issues/81) 的 Nginx 靜態前端預覽與同源 API 僅適用本機 Compose，FastAPI 互動文件仍由 `127.0.0.1:8000/docs` 直接存取，不經 `/api/docs` 提供；M4 的雲端前端託管、映像發布、DNS 與 TLS 仍需另行規劃與驗收。

前端中英語系切換（[GitHub #80](https://github.com/shiroki9979/shiro-mlops/issues/80)）已隨 [PR #88](https://github.com/shiroki9979/shiro-mlops/pull/88) 合併，未另立里程碑。

---

## 架構改善評估

[2026-09-27 架構檢視紀錄](explanation/2026-09-27-architecture-review.md) 保存三項架構改善候選：
集中營運資料檢視器分頁規則、集中預報版本選取與降級解析，以及收攏營運資料檢視器查詢生命週期。
分頁規則已完成 Q1 至 Q8 的設計討論，並依 [GitHub #72](https://github.com/shiroki9979/shiro-mlops/issues/72) 實作 v2 cursor、精確閉區間與八資料集共用查詢路徑。
五張工單 [#73](https://github.com/shiroki9979/shiro-mlops/issues/73)、[#74](https://github.com/shiroki9979/shiro-mlops/issues/74)、[#75](https://github.com/shiroki9979/shiro-mlops/issues/75)、[#76](https://github.com/shiroki9979/shiro-mlops/issues/76)、[#77](https://github.com/shiroki9979/shiro-mlops/issues/77) 均已完成，依序涵蓋共用流程與觀測批次、預報、逐時資料、供需與機組、精確窗口及舊流程退場。
SQLite 與隔離本機 TimescaleDB 驗收方式見 [操作文件](how-to/verify-data-explorer-pagination.md)。
查詢生命週期已依 [GitHub #103](https://github.com/shiroki9979/shiro-mlops/issues/103) 收攏至前端單一查詢 hook：預設窗口、cursor 失效、URL 同步與回第一頁的快取清除集中處理，畫面只表達使用者操作。
集中預報版本選取與降級解析維持待評估，證據與取捨詳見架構檢視紀錄。

## 待辦與驗收焦點

1. **M6 營運驗收**：依[冷啟動驗收指南](how-to/recover-training-after-load-cold-start.md)第 5 節，以 `make smoke-check ARGS="--require-ready --task dynamic_horizon_forecast"` 確認有效逐時觀測達 672 小時，完成首次訓練並確認 `/ready` 回傳 HTTP 200；smoke check 輸出、訓練 run ID 與 `/ready` 回應留於 [GitHub #60](https://github.com/shiroki9979/shiro-mlops/issues/60)。驗收只看門檻，不含累積穩定性；目前沒有正式環境的驗收結果。
2. **M7 營運驗收**：`load_pattern_anomaly`（672 小時）與 `high_load_alert`（1344 小時）各自以 `--task <task_id>` 驗收排程、首次訓練與 `POST /tasks/{task_id}/predict`、`GET /tasks/{task_id}/ready` 就緒，與 M6 分開結案。
3. **M3 加權天氣與放假日**：設計已於 2026-11-16 定案（[ADR-0012](adr/0012-combine-weather-reference-points-into-weighted-weather.md)、[GitHub #95](https://github.com/shiroki9979/shiro-mlops/issues/95)）。能力段 TICKET-301／302 已隨 [PR #105](https://github.com/shiroki9979/shiro-mlops/pull/105) 合併，三個任務的 TOML 未變。採用段 TICKET-303 的離線工具已備妥（`lab.regional_weights` 推算權重、`lab.snapshot --variant` 凍結候選天氣快照、`lab.origins` 盤點合格起點，見 [lab 研究指南](how-to/run-lab-study.md)；研究腳本位於 [`lab/2026-11-17-dhf-weather-calendar/`](../lab/2026-11-17-dhf-weather-calendar/README.md)），待正式資料庫的有效評估起點至少涵蓋 7 個日曆日後執行回測。
4. **M4 雲端與治理**：Terraform 宣告已存在；CI 執行 Python lint／test、前端 lint／test／build，以及本機 Nginx 映像建置與 smoke check（[#81](https://github.com/shiroki9979/shiro-mlops/issues/81)），但未發布 Docker／ECR 映像。本機 Compose 已可經 Nginx 預覽已建置的前端，Terraform 仍無前端託管資源，現有部署工單亦未涵蓋前端上線；需另決定雲端託管方式與 API 路由後才能排入部署管線。Rulesets 與分支保護 API 對此私人儲存庫回傳方案限制的 HTTP 403，設定狀態待可用權限核對，TICKET-401／402 不列為完成。預報檢視 `/history` 改呈現預報實績（[ADR-0013](adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md)）：TICKET-403／404 與雲端通道無關，可先行實作以盡早累積。工程主控台只留地端，前端拆成預報檢視與工程主控台兩個應用（[ADR-0014](adr/0014-keep-engineering-console-local-and-split-frontend-apps.md)）：TICKET-406 可先行實作；雲端部署工單依賴 TICKET-406。雲端只公開預先算好的預報，地端負責全部運算（[ADR-0015](adr/0015-publish-forecast-view-as-static-precomputed-output.md)，取代 ADR-0001）：TICKET-408 匯出已發布產物，TICKET-405／409 讓預報檢視改讀匯出 JSON，TICKET-410／411 收斂 Terraform 與移除 `ENVIRONMENT=aws`；TICKET-407 因雲端沒有 FastAPI 而不再需要。CloudFront 經 OAC 從 S3 提供預報檢視，SPA fallback 用 CloudFront Function、不做 invalidation（[#128](https://github.com/shiroki9979/shiro-mlops/issues/128)，[SPEC §8](SPEC.md#8-預報檢視的雲端託管)）：TICKET-412。Terraform state 待 [#129](https://github.com/shiroki9979/shiro-mlops/issues/129) 決定後再切 CD 工單。

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

### Milestone 3: 加權天氣與放假日特徵 ([GitHub #95](https://github.com/shiroki9979/shiro-mlops/issues/95))

> 依 [ADR-0009](adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md) 與 [ADR-0012](adr/0012-combine-weather-reference-points-into-weighted-weather.md)，以任務設定的加權氣象代表點與放假日開關實作。分為能力（TICKET-301、302）與採用（TICKET-303）兩段；能力段完成時三個任務的 TOML 不變。

#### [TICKET-301] 放假日特徵 ([GitHub #96](https://github.com/shiroki9979/shiro-mlops/issues/96))

- **目標**：由任務設定開啟 `is_day_off`，依政府行政機關辦公日曆判定目標小時是否為放假日（含補假，不含颱風假），從訓練、遞迴預報到 Feast 匯出一致實作。
- **完成標準 (DoD)**：`holidays` 套件鎖版加入依賴；官方 2026 年 16 個平日放假日 fixture 與跨越放假日的遞迴預報測試通過；開關預設關閉，既有測試不修改即通過；`docs/SPEC.md` 同步更新。

#### [TICKET-302] 多氣象代表點加權天氣 ([GitHub #97](https://github.com/shiroki9979/shiro-mlops/issues/97))

- **目標**：任務設定可列多個氣象代表點與權重，訓練、serving、API 與 Feast 一致以加權天氣作為天氣輸入；任一點降級即整次降級，任一點無替代資料即回傳 HTTP 503。
- **完成標準 (DoD)**：權重驗證、逐點降級彙整、503、訓練與 serving 加權值一致、逐點缺口下訓練表往返無損，以及依代表點揭露的 `weather_sources` 皆有離線測試；三個任務的 TOML 不變；`docs/SPEC.md` 同步更新。

#### [TICKET-303] M3 採用研究 ([GitHub #98](https://github.com/shiroki9979/shiro-mlops/issues/98))

- **目標**：在 lab 以區域供需快照的北中南用電占比推算權重，比較基線、放假日、三點加權與兩者合併四個候選，判定 `dynamic_horizon_forecast` 是否採用。
- **完成標準 (DoD)**：研究報告依 #89 格式記錄快照、權重期間、各提前時數的 MAPE 與訓練列損失；評估起點至少涵蓋 7 個日曆日且贏過基線才修改 TOML，並同步把儀表板天氣欄位改為「加權氣溫／加權濕度」。

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

#### [TICKET-403] 定時發布已發布預報 ([GitHub #130](https://github.com/shiroki9979/shiro-mlops/issues/130))

- **目標**：依 [ADR-0013](adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md) 由地端 Dagster 資產每小時發布動態視界預報，作為預報實績的原始紀錄。
- **功能範圍**：
  1. 新增已發布預報的保存結構：發布時刻、負載起點、運行狀態、模型版本識別、目標小時與預測負載；寫入後不可更新。
  2. 新增每小時執行的發布資產：以發布時刻為 `as_of`、$H = 168$，沿用 `predict_task` 的降級與負載起點過舊規則；無法產出時不寫入、不補發；模型健康檢查為 `WARNING` 時照常發布。
  3. 定義不依賴 MLflow 的模型版本識別，MLflow 版本另作附註，並更新 SPEC。
- **完成標準 (DoD)**：
  - 離線測試涵蓋：已發布預報不可覆寫、隨需 `/predict` 不寫入、負載起點過舊時沒有紀錄、MLflow 不可用時仍有版本識別。
  - SPEC 記錄保存結構、資產與排程。

#### [TICKET-404] 預報實績彙整 ([GitHub #130](https://github.com/shiroki9979/shiro-mlops/issues/130))

- **目標**：依 ADR-0013 以地端資產將已發布預報對照全台逐時實際負載，產出預報檢視所需的預報實績。
- **相依**：TICKET-403。
- **功能範圍**：
  1. 提前時數自發布時刻起算，不大於 0 的步數不計入；只配對有有效逐時觀測的目標小時；降級預報照常計入。
  2. 以目標小時判斷最近 30 天的滾動窗，產出提前時數 1–168 的 MAPE 與 MAE、提前 24 小時的 MAPE 與 MAE，以及提前 24 小時預報與實際負載的時序配對。
  3. 輸出累積天數；有配對的目標日未滿 7 天時不產出指標。輸出不含運行狀態、天氣來源、模型版本與資料缺口。
- **完成標準 (DoD)**：
  - 離線測試以 fixtures 涵蓋上列計入規則、30 天窗邊界與 7 天門檻。
  - SPEC 記錄輸出格式。

#### [TICKET-405] 預報檢視 `/history` 接上預報實績 ([GitHub #130](https://github.com/shiroki9979/shiro-mlops/issues/130)、[#127](https://github.com/shiroki9979/shiro-mlops/issues/127))

- **目標**：以 TICKET-408 匯出的預報實績 JSON 取代 `/history` 的前端合成資料（[ADR-0015](adr/0015-publish-forecast-view-as-static-precomputed-output.md) §2.4–2.5）。
- **相依**：TICKET-406、TICKET-408。
- **功能範圍**：
  1. MAPE 與 MAE 指標卡（提前 24 小時）、MAPE 對提前時數曲線（MAE 於 tooltip）、提前 24 小時預報與實際負載的 30 天時序圖。
  2. 累積未滿 7 天時顯示空狀態與累積天數。
  3. 移除尖峰命中率卡、RMSE 卡、結論卡、沒有出處的基準值、模型名稱與「滾動回測」文案；中英文案改用「預報實績」。
  4. 顯示統計截至時刻；距觀眾當下超過 24 小時時顯示中性提示，不揭露原因。
  5. 資料自 `/published/` 下的 JSON 讀取，不呼叫任何 API。
  6. 非 2xx、網路錯誤或 JSON 解析失敗時顯示中性的錯誤狀態，不區分原因；空狀態只由 JSON 內容決定（[SPEC §8.4](SPEC.md#84-前端讀取-published)）。
  7. Vite dev server 以 proxy 把 `/published` 轉送到地端 Nginx（`:8080`）；與 TICKET-409 由先實作者新增。
- **完成標準 (DoD)**：
  - Vitest 涵蓋有資料、空狀態、超過 24 小時提示與讀取失敗四種畫面；前端不再產生任何合成資料，也不呼叫 API。

#### [TICKET-406] 前端拆成預報檢視與工程主控台兩個應用 ([GitHub #126](https://github.com/shiroki9979/shiro-mlops/issues/126))

- **目標**：依 [ADR-0014](adr/0014-keep-engineering-console-local-and-split-frontend-apps.md) 把 `frontend/` 改為 pnpm workspace，讓雲端只建置與部署預報檢視。
- **功能範圍**：
  1. 建立 `apps/forecast-view`（`/`、`/history`）、`apps/engineering-console`（base path `/console/`，含 `/console/monitoring`、`/console/settings`、`/console/data/*`）與 `packages/shared`；兩個應用各有自己的 `package.json`，彼此不得 import。
  2. `shared` 只收 ADR-0014 §2.3 的項目：shadcn UI 元件、設計 token 與 Tailwind 基底、i18n 機制與語系切換元件、SPEC §6.4 格式函式、`request()` 與 `ApiError`。`useMessages` 改為由各應用傳入字典的工廠函式；字典、API 端點與 schema、外框與頁面元件留在各應用。
  3. 語系切換移到兩個應用的外框，`/settings` 不再提供語系選單；API 健康徽章、側欄狀態卡與營運資料檢視器導覽只在工程主控台。
  4. 地端 Nginx 同一來源提供兩個應用：預報檢視在根路徑，工程主控台在 `/console/`，`/api/` 轉送維持一份；舊網址不轉址。
  5. 更新 Dockerfile、Compose、CI 與 SPEC §6（語系選擇入口與 `frontend/` 結構）。
- **完成標準 (DoD)**：
  - ESLint 禁止 `apps/*` 互相 import，也禁止 `packages/shared` import 任何應用。
  - CI 驗證預報檢視的建置產物不含 `/console`、`/monitoring`、`/data/` 路徑與工程主控台專用相依。
  - 既有 Vitest 測試依歸屬移入各應用與 `shared` 並全數通過；兩個應用都有語系切換的整合測試。
  - 地端 Nginx smoke check 涵蓋 `/`、`/history` 與 `/console/`。

#### [TICKET-407] 雲端拒絕開放工程主控台 API ([GitHub #126](https://github.com/shiroki9979/shiro-mlops/issues/126))

> **不再需要**：[ADR-0015](adr/0015-publish-forecast-view-as-static-precomputed-output.md) 決定雲端沒有 FastAPI，且 `ENVIRONMENT` 的 `aws` 值由 TICKET-411 移除，本工單的前提不成立。日後雲端若加 API，依 ADR-0014 §2.1 另行實作。以下保留原內容備查。

- **目標**：依 ADR-0014 §2.1，讓 API 在雲端環境不可能開放營運資料檢視器讀取面。
- **功能範圍**：
  1. API 啟動時，若 `ENVIRONMENT=aws` 且 `DATA_EXPLORER_ENABLED=true`，直接啟動失敗並寫明原因。
  2. SPEC §2.1 記錄此限制。
- **完成標準 (DoD)**：
  - 離線測試涵蓋：`ENVIRONMENT=aws` 且 `DATA_EXPLORER_ENABLED=true` 時啟動失敗；`ENVIRONMENT=local` 時照常開放。

#### [TICKET-408] 匯出預報檢視的已發布產物 ([GitHub #127](https://github.com/shiroki9979/shiro-mlops/issues/127))

- **目標**：依 [ADR-0015](adr/0015-publish-forecast-view-as-static-precomputed-output.md) §2.3–2.4，由地端 Dagster 資產把最新已發布預報與預報實績匯出為預報檢視的公開 JSON。
- **相依**：TICKET-403、TICKET-404。
- **功能範圍**：
  1. 新增位於已發布預報與預報實績之後、每小時執行的匯出資產；一律寫入地端目錄，有設定 S3 時再上傳到資料 prefix，覆寫固定檔名。
  2. 最新已發布預報只輸出預報時刻、目標小時與預測負載，且只含目標小時晚於預報時刻的步；預報實績輸出 ADR-0013 §2.3 的公開欄位與統計截至時刻。
  3. 地端 Nginx 以 `/published/` 提供地端目錄並回 `Cache-Control: public, max-age=60`（[SPEC §8.2](SPEC.md#82-origin-與-behavior)）；Compose 掛載該目錄。
  4. SPEC 記錄兩份 JSON 的格式、檔名、資產與排程，以及地端上傳用的設定項目（不含 key 值）。
- **完成標準 (DoD)**：
  - 離線測試涵蓋：沒有 S3 設定時只寫地端目錄；以 mock 驗證 S3 上傳；輸出不含運行狀態、負載起點、天氣值、天氣來源與模型版本；目標小時不晚於預報時刻的步不輸出；還沒有已發布預報時的輸出。
  - 地端 Nginx smoke check 涵蓋 `/published/` 下的兩份 JSON，以及 `/published/` 下不存在的檔案不回 200。

#### [TICKET-409] 預報檢視 `/` 改讀最新已發布預報 ([GitHub #127](https://github.com/shiroki9979/shiro-mlops/issues/127))

- **目標**：依 ADR-0015 §2.4–2.5，讓 `/` 顯示 TICKET-408 匯出的最新已發布預報，不再呼叫 `/predict`。
- **相依**：TICKET-406、TICKET-408。
- **功能範圍**：
  1. 資料自 `/published/` 下的 JSON 讀取；移除 `/predict` 呼叫。
  2. 移除加權氣溫與濕度的曲線、切換、指標卡與明細欄位，只呈現預測負載。
  3. 保留視界預設按鈕，以預報時刻為起點截取；「一週」顯示該份預報涵蓋的全部未來小時。
  4. 顯示預報時刻；距觀眾當下超過 24 小時時顯示中性提示，不揭露原因；還沒有已發布預報時顯示空狀態。
  5. 非 2xx、網路錯誤或 JSON 解析失敗時顯示中性的錯誤狀態，不區分原因；空狀態只由 JSON 內容決定（[SPEC §8.4](SPEC.md#84-前端讀取-published)）。
  6. Vite dev server 以 proxy 把 `/published` 轉送到地端 Nginx（`:8080`）；與 TICKET-405 由先實作者新增。
- **完成標準 (DoD)**：
  - Vitest 涵蓋：有資料、空狀態、超過 24 小時提示、讀取失敗；視界截取以預報時刻為起點，不隨觀眾當下改變；建置產物不含 `/predict` 呼叫。

#### [TICKET-410] Terraform 收斂為預報檢視的靜態託管 ([GitHub #127](https://github.com/shiroki9979/shiro-mlops/issues/127))

- **目標**：依 ADR-0015 §2.2、§2.6 移除不再需要的雲端資源，補上地端上傳權限、保存規則與成本護欄。CloudFront 由 TICKET-412 處理；state backend 由 [#129](https://github.com/shiroki9979/shiro-mlops/issues/129) 的工單處理。
- **功能範圍**：
  1. 移除 `aws_ecr_repository.api`、`aws_ecr_repository.dagster`、App Runner instance role 與其 S3 policy attachment，以及 CI 角色中的 ECR 權限與相關 outputs。
  2. bucket 改名為 `shiro-mlops-forecast-view`（仍以變數傳入），移除 Data Lake、Feast Registry 與 MLflow 的用途註解；依 [SPEC §8.1](SPEC.md#81-s3-配置與寫入權限)，前端產物放 `site/`、匯出 JSON 放 `published/`，CI 角色的 S3 寫入限定 `site/*`。
  3. 新增地端上傳用 IAM 使用者：只允許 `PutObject` 到 `published/*`，沒有刪除與其他 prefix 的權限；access key 不由 Terraform 產生或輸出。
  4. S3 bucket 保留 versioning，加上舊版本 30 天後過期的 lifecycle 規則。
  5. 新增 AWS Budgets：月實際支出 5 美元、預測支出 10 美元時寄 email 警示（收件地址以變數傳入）。
  6. 改寫 [AWS 部署指南](how-to/deploy-aws-infrastructure.md)，移除 ECR 與 App Runner，加入地端 key 的建立與輪替步驟。
- **完成標準 (DoD)**：
  - `terraform fmt -check` 與 `terraform validate` 通過；Terraform 中沒有 ECR、App Runner 或運算資源。
  - 地端 IAM 使用者的 policy 經審查只含 `published/*` 的寫入權限；CI 角色的 S3 寫入只含 `site/*`。

#### [TICKET-411] 移除 `ENVIRONMENT=aws` 與 S3 I/O 分支 ([GitHub #127](https://github.com/shiroki9979/shiro-mlops/issues/127))

- **目標**：依 ADR-0015 §2.2，移除不再有部署目標的 `aws` 環境值，以及它切換的 Dagster I/O manager 與特徵 Parquet S3 分支。
- **功能範圍**：
  1. `ENVIRONMENT` 只保留 `local` 與 `test`；移除 `core/config.py` 的 S3 特徵路徑與 `core/io_managers.py`、`features/storage.py` 的 `s3://` 分支及其測試。
  2. 匯出資產的 S3 上傳（TICKET-408）以獨立設定啟用，不依賴 `ENVIRONMENT`。
  3. SPEC 與 `.env` 範例移除 `aws` 環境與相關設定；ROADMAP 註明 TICKET-407 不再需要。
- **完成標準 (DoD)**：
  - `uv run pytest tests/ -v` 與 ruff 通過；程式碼中沒有 `ENVIRONMENT == "aws"` 的分支。

#### [TICKET-412] CloudFront 託管預報檢視 ([GitHub #128](https://github.com/shiroki9979/shiro-mlops/issues/128))

- **目標**：依 [SPEC §8](SPEC.md#8-預報檢視的雲端託管)，以 CloudFront 經 OAC 從 S3 提供預報檢視與匯出 JSON，同一個 AWS 預設網址下 `/`、`/history` 可直接開啟，`/published/` 缺檔時照實回錯誤。
- **相依**：TICKET-410。
- **功能範圍**：
  1. Distribution：同一 bucket 的 `site`（origin path `/site`）與 `published` 兩個 origin，預設、`/assets/*`、`/published/*` 三個 behavior；`PriceClass_200`、`redirect-to-https`、gzip 與 Brotli、HTTP/2 與 HTTP/3、預設 `*.cloudfront.net` 憑證；不設 WAF、地理限制與標準 log。
  2. Cache policy 與 response headers policy 依 SPEC §8.2 的表格設定 TTL 與瀏覽器 `Cache-Control`；三個 behavior 都套用 AWS 托管 `SecurityHeadersPolicy` 的安全標頭。
  3. `infra/terraform/functions/spa-rewrite.js`（viewer-request，只掛在預設 behavior），把最後一段沒有副檔名的路徑改寫為 `/index.html`；不使用 custom error response。
  4. bucket policy 只授權該 distribution 經 OAC 的 `s3:GetObject`，不授權 `s3:ListBucket`。
  5. SPEC §8.5 的雲端 smoke check 項目寫成可執行的腳本，供 CD 工單呼叫。
  6. 改寫 [AWS 部署指南](how-to/deploy-aws-infrastructure.md)，加入 CloudFront 網址的取得方式。
- **完成標準 (DoD)**：
  - `spa-rewrite.js` 的 `node --test` 離線測試涵蓋 `/`、`/history`、`/history/`、`/assets/x.js`、`/favicon.ico`、`/console/foo`，並在 CI 執行。
  - `terraform fmt -check` 與 `terraform validate` 通過；沒有 custom error response、WAF 與運算資源。
  - 實際部署後（依 #129 的 apply 權責）smoke check 通過：首頁、`/history` 回 200 且為 HTML；兩份 JSON 回 200 且預報時刻不超過 24 小時；`/published/` 下不存在的檔案不回 200。

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

> 依 [ADR-0008](adr/0008-derive-hourly-actual-load-from-regional-snapshots.md)，放棄尋找可回補的官方歷史來源（[GitHub #58](https://github.com/shiroki9979/shiro-mlops/issues/58) not planned）。本里程碑只保證有效逐時觀測達門檻後可以訓練；M3 與 M8 的採用研究另需評估起點涵蓋至少 7 個日曆日，由 TICKET-303 與 TICKET-803 的完成標準要求，不由本里程碑保證。

#### [TICKET-601] 由區域快照推算全台逐時實際負載 ([GitHub #59](https://github.com/shiroki9979/shiro-mlops/issues/59))

- **目標**：以區域供需快照四區加總的小時平均取代已失效的 d015046，恢復 `raw_taipower_load`。
- **完成標準 (DoD)**：`hourly_actual_load_job` 冪等產出符合有效樣本與 4／6 完整度門檻的逐時值；區域快照改為指數退避重試；d015046 路徑與舊資料列已移除；推算規則離線測試通過。

#### [TICKET-602] 恢復排程式訓練與 drift ([GitHub #60](https://github.com/shiroki9979/shiro-mlops/issues/60))

- **目標**：負載入庫恢復後，每日訓練與每小時 drift 回到可操作驗證狀態。
- **完成標準 (DoD)**：排程不再固定暫停；有效逐時觀測少於 672 小時時訓練明確拒絕；container smoke check 與操作文件完成。

---

### Milestone 7: ML 任務解耦 (ML Task Decoupling) ([GitHub #64](https://github.com/shiroki9979/shiro-mlops/issues/64))

> 依 [ADR-0009](adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md) 與 [ADR-0010](adr/0010-persist-models-in-native-non-executable-formats.md)；M6 累積 672 個有效逐時觀測期間進行，完成後接續 M3。

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

---

### Milestone 8: 研究空間 (Lab) ([GitHub #89](https://github.com/shiroki9979/shiro-mlops/issues/89))

> 依 [ADR-0011](adr/0011-co-locate-lab-workspace-with-unidirectional-dependency.md)，`lab/` 作為 `uv` workspace 成員單向依賴 `shiro_mlops`，提供訓練表快照、滾動起點回測與超參數搜尋空間。

#### [TICKET-800] 訓練表序列化改為無損：保留負載缺時的氣象列 ([GitHub #93](https://github.com/shiroki9979/shiro-mlops/issues/93))

- **目標**：將 `training_table` 改為以負載與觀測氣象時間軸的聯集序列化，消除負載缺時丟失氣象列造成的向後補值偏差。
- **完成標準 (DoD)**：負載與氣象缺口錯開時，經 `training_table`／`training_data_from_table` 往返的 `TrainingData` 與訓練出的模型皆與直接查庫一致；`docs/SPEC.md` 同步更新。

#### [TICKET-801] 建立 lab workspace 與快照指令 ([GitHub #90](https://github.com/shiroki9979/shiro-mlops/issues/90))

- **目標**：建立 `lab/` workspace 成員與 `python -m lab.snapshot` 指令，將指定 ML 任務於 `as_of` 時刻的訓練表凍結為不可覆寫快照。
- **完成標準 (DoD)**：根目錄 `uv sync --all-extras` 不安裝 `lab` 依賴；`write_snapshot`／`read_snapshot` 往返無損、拒絕覆寫且原樣傳遞 `TaskNotReady`；CI 執行 `lab/tests`；完成 [ADR-0011](adr/0011-co-locate-lab-workspace-with-unidirectional-dependency.md)、`AGENTS.md` 與本里程碑登錄。

#### [TICKET-802] 滾動起點回測與基線報告 ([GitHub #91](https://github.com/shiroki9979/shiro-mlops/issues/91))

- **目標**：於 `lab/` 實作純函式 `rolling_origin_backtest`，對 `dynamic_horizon_forecast` 快照產出基線回測報告與操作指南。
- **完成標準 (DoD)**：起點有效性檢查、訓練截斷與觀測氣象對齊通過離線單元測試；產出第一個研究主題的基線 `README.md` 與 `docs/how-to/` 研究指南。

#### [TICKET-803] dynamic_horizon_forecast 超參數與特徵配方研究 ([GitHub #92](https://github.com/shiroki9979/shiro-mlops/issues/92))

- **目標**：以 Optuna 結合滾動起點回測搜尋 `dynamic_horizon_forecast` 的 LightGBM 超參數與特徵配方（`lags`、`rolling_windows`），分離搜尋起點與評估起點。
- **完成標準 (DoD)**：完成 Jupytext `.py` 研究腳本、MLflow `lab/dhf-hyperparameter-search` 紀錄與研究報告結論；依評估起點判定是否更新任務設定 TOML。
