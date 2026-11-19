# ADR 0001: 混合雲地架構之權責邊界切分

- 建立日期：2026-08-23
- 最後更新：2026-11-19
- 狀態：已被 [ADR-0015](0015-publish-forecast-view-as-static-precomputed-output.md) 取代 (Superseded)

---

## 脈絡 (Context)

本專案旨在建立一個能兼顧「地端高算力/無雲端長時運算費用」與「雲端高可用服務對外暴露」的 MLOps 混合架構。需要決定資料擷取、模型訓練、實驗追蹤、特徵快取與 API 推論服務的雲/地權責邊界。

---

## 決策 (Decision)

採用 **「地端執行重運算 + 雲端 Serverless 服務與集中儲存」** 的拓撲結構：

1. **地端 Worker / 本地環境**：
   - 負責執行資料爬取 (Taipower, CWA API)、特徵工程轉換、Feast 實體化與 LightGBM 模型訓練。
   - 透過 Docker Compose 提供全地端封閉運行的能力（包含本地 PostgreSQL, Redis, Dagster, MLflow），供無公網或地端 MLOps 研發驗證。
2. **AWS 雲端層**：
   - **S3** 作為集中式 Data Lake、Feast Registry (`s3://.../registry.pb`) 與 MLflow Artifacts 儲存。
   - **App Runner / ECS Fargate** 託管 FastAPI 隨需推論服務，具備縮容至零（Scale to Zero）與免維護負載平衡特性。
   - **GitHub Actions + AWS IAM OIDC** 建立自動化 CI/CD 閘門。

---

## 取捨分析 (Trade-offs)

### 優點

- **極低營運成本**：重運算（資料清洗與模型擬合）全由地端負擔，雲端僅保留 S3 與 Serverless API，避免長駐高規格 GPU/CPU 實例支出。
- **高可用對外服務**：推論服務託管於 AWS，不需在地端設定複雜的 Port Forwarding 或動態 DNS。
- **地端 MLOps 經驗累積**：全地端 Docker Compose 設定可直接借鏡於企業內部封閉式 MLOps 機房建設。

### 成本與風險

- **跨網資料傳輸**：地端產出的特徵與模型 artifact 需上傳至 S3，需維持穩定網路連線與 Service Account / IAM 認證。
- **配置多樣性**：需維護 Local FS 與 S3 的 I/O Manager 映射。

### 適用情境

- 適合個人/團隊擁有本地工作站算力，但需對外提供雲端 API 與統一資料資產存取之場景。

---

## Notes

- 2026-11-19：由 [ADR-0015](0015-publish-forecast-view-as-static-precomputed-output.md) 取代。雲端不再託管 FastAPI 隨需推論，S3 也不再作為 Data Lake、Feast Registry 或 MLflow artifacts 儲存；雲端只公開預報檢視。本文保留原決策，不以歷史改寫。
