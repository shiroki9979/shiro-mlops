# 專案發展藍圖與任務清單 (ROADMAP.md)

- 建立日期：2026-08-23
- 最後更新：2026-09-03
- 專案版本：`0.1.0`

本文檔定義 `shiro-mlops` 的階段性里程碑（Milestones）與各項 Tracer-Bullet 工單，每個工單皆為具備獨立完成標準（Definition of Done, DoD）的垂直切片。

---

## 里程碑總覽 (Milestone Overview)

| 里程碑 | 目標 | 主要模組 | 驗證標準 |
| :--- | :--- | :--- | :--- |
| **M1: 視覺化儀表板** | 實作 React 19 SPA 現代化儀表板，對接 FastAPI 隨需預測 | `frontend/` | 成功啟動並通過 Vitest 測試與 Vite 生產打包建置 (已完成) |
| **M2: API 穩健度與降級快取** | 建立本地快取與自動重試，落實降級預報模式 | `src/shiro_mlops/data/` | 斷網條件下仍能產出標記 `DEGRADED` 之預測 |
| **M3: 多測站與行事曆特徵** | 納入全台三區測站溫度加權與台灣節假日特徵 | `src/shiro_mlops/features/` | 特徵矩陣擴充且單元測試通過，MAPE 指標提升 |
| **M4: 雲端部署與 CI/CD** | Terraform 基礎設施部署、GitHub Rulesets 與 CI/CD 串接 | `infra/terraform/`, `.github/` | PR Merge 自動建置 ECR 映像檔，主分支與標籤保護生效 |

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
  - 執行 `npm run test` 全數通過（Vitest + MSW v2 離線測試）。
  - 執行 `npm run build`（`tsc -b && vite build`）與 `npm run lint` 無報錯。

---

### Milestone 2: 資料客戶端穩健度與降級快取 (API Resiliency)

#### [TICKET-201] 實作 Taipower 與 CWA 本地 Parquet 快取與重試

- **目標**：當外部 API 斷線或連線超時時，自動切換讀取本地最新快照。
- **功能範圍**：
  1. `TaipowerClient` 與 `CWAClient` 加入本地 Parquet 快取機制。
  2. 加入指數退避重試（Exponential Backoff）。
  3. 當氣象資料無法更新時，自動啟用常模補值並於 API 回應標記 `status: "degraded"`。
- **完成標準 (DoD)**：
  - 新增 `tests/integration/test_resiliency.py`，模擬外部 API 500 錯誤時，仍能正確回傳降級預報。

---

### Milestone 3: 多測站與節假日特徵工程深化

#### [TICKET-301] 擴充全台三區測站溫度加權與行事曆特徵

- **目標**：提高預測精度，反映北中南用電重鎮氣候差異。
- **功能範圍**：
  1. CWA 抓取台北 (466920)、台中 (467490)、高雄 (467440) 測站氣溫。
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
