# ADR 0004: 採用 Dagster 軟體定義資產 (SDA) 作為核心資料與模型編排引擎

> - Created: 2026-08-23
> - Last Updated: 2026-11-27
> - Status: Accepted

---

## 脈絡 (Context)

MLOps 需要統一協調外部資料抓取 (Taipower/CWA)、特徵管線、Feast 實體化、模型重新訓練 (MLflow)、以及事後漂移評估。傳統工作流引擎（如 Airflow）以 Task DAG 為核心，缺乏對資料產出物（Data Assets）與儲存媒介（I/O Managers）的宣告式抽象。

---

## 決策 (Decision)

採用 **Dagster Software-Defined Assets (SDA)** 作為編排框架：

1. **宣告式資產**：將 `raw_taipower_load_data`、`raw_weather_obs_data`、`engineered_features`、`trained_forecaster_model` 與 `drift_monitoring_report` 定義為明確資產節點。
2. **I/O Manager 解耦**：透過自訂 `ParquetIOManager`，讓資產計算邏輯完全無關乎實際存儲位置（地端目錄 vs S3 Bucket）。

---

## 取捨分析 (Trade-offs)

### 優點

- **資產依賴圖與可觀察性**：在 Dagster UI 的 lineage 檢視中清晰可見從 Raw API 至 Drift Report 的資產依賴圖。
- **環境隔離與測試性**：資產為標準 Python 函式，容易單獨撰寫單元測試或透過 Mock Fixture 驗證。
- **儲存抽換無痛**：由環境變數切換 Local Parquet 與 S3，業務程式碼不需寫死儲存路徑。

### 成本與風險

- **概念學習曲線**：需熟悉 Dagster 的 Asset, Partition, Resource 體系。

### 適用情境

- 現代化 Data Lakehouse 與重視資料品質、需追蹤資產依賴圖之 MLOps 架構。
