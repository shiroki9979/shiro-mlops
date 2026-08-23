# 專案發展藍圖與任務清單 (ROADMAP.md)

- 建立日期：2026-08-23
- 最後更新：2026-08-23
- 專案版本：`0.1.0`

本文檔定義 `shiro-mlops` 的階段性里程碑（Milestones）與各項 Tracer-Bullet 工單，每個工單皆為具備獨立完成標準（Definition of Done, DoD）的垂直切片。

---

## 里程碑總覽 (Milestone Overview)

| 里程碑 | 目標 | 主要模組 | 驗證標準 |
| :--- | :--- | :--- | :--- |
| **M1: 視覺化儀表板** | 實作 Streamlit 互動介面，對接 FastAPI 隨需預測 | `frontend/app.py` | 成功啟動並渲染 24h 動態視界負載與氣溫圖表 |
| **M2: API 穩健度與降級快取** | 建立本地快取與自動重試，落實降級預報模式 | `src/shiro_mlops/data/` | 斷網條件下仍能產出標記 `DEGRADED` 之預測 |
| **M3: 多測站與行事曆特徵** | 納入全台三區測站溫度加權與台灣節假日特徵 | `src/shiro_mlops/features/` | 特徵矩陣擴充且單元測試通過，MAPE 指標提升 |
| **M4: 雲端部署與 CI/CD** | Terraform 基礎設施部署與 GitHub Actions 串接 | `infra/terraform/`, `.github/` | PR Merge 自動建置 ECR 映像檔並更新服務 |

---

## 詳細工單規格 (Tracer-Bullet Tickets)

### Milestone 1: 視覺化儀表板實作 (Frontend Dashboard)

#### [TICKET-101] 建立 Streamlit 互動式儀表板

- **目標**：取代 `frontend/` 靜態 stub，建立 Python 原生 Streamlit 應用程式。
- **功能範圍**：
  1. 側邊欄控制項：可自訂預測視界長度（1 ~ 168 小時）與預測區域（Taipei）。
  2. 負載預報曲線圖：呼叫 `/predict` 端點繪製未來 $H$ 小時之負載變化趨勢。
  3. 氣象預報疊圖：同步繪製未來氣溫與相對濕度折線圖。
  4. 系統健康指標：呼叫 `/health` 顯示 API 版本、環境與模型載入狀態。
- **完成標準 (DoD)**：
  - 建立 `frontend/app.py` 與 `frontend/requirements.txt`（或包含於 pyproject）。
  - 執行 `uv run streamlit run frontend/app.py` 無報錯且能正常呈現圖表。

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
