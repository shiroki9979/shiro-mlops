# 如何在全地端運行完整 MLOps 容器化環境

> [!NOTE]
> **Diátaxis 象限鎖定**
>
> - **目標象限**：How-To Guide
> - **目標讀者**：具備 Docker 與 MLOps 基本概念的工程師
> - **核心目標**：指引如何在全地端無外部依賴環境下啟動並驗證完整 Docker Compose MLOps Stack
> - **排除內容（Avoid）**：零基礎 Python 教學、詳細的時序演算法數學推導

本指南說明如何透過 Docker Compose 一鍵拉起包含 PostgreSQL、Redis (Feast Online Store)、MLflow Tracking Server、Dagster 與 FastAPI 的全地端工作環境。

---

## 1. 前置需求

- 已安裝 Docker 與 Docker Compose (v2.0+)
- 本機可用記憶體建議 $\ge 4 \text{ GB}$

---

## 2. 啟動所有服務

先在專案根目錄準備本機環境變數，並填入 `CWA_API_KEY`；`.env` 已被 Git 忽略：

```bash
cp .env.example .env
# 編輯 .env，將 CWA_API_KEY= 設為實際授權碼
```

在專案根目錄執行：

```bash
make compose-up
```

或使用原生 docker compose 指令：

```bash
docker compose -f docker/docker-compose.yml up -d
```

---

## 3. 服務端口與健康驗證

服務啟動後，各元件端點如下：

| 元件名稱 | 容器名稱 | 監聽端口 | 驗證方式 |
| :--- | :--- | :--- | :--- |
| **React 視覺化儀表板** | 本地 SPA (`make frontend`) | `http://localhost:5173` | 瀏覽器開啟檢視 1~72h 負載雙軸預測圖表與監控 |
| **Dagster Webserver** | `shiro_dagster_webserver` | `http://localhost:3000` | 瀏覽器開啟檢視資產依賴圖與排程（Compose 映射 `3000`） |
| **MLflow Server** | `shiro_mlflow` | `http://localhost:5001` | 瀏覽器開啟檢視實驗指標與 Model Registry |
| **FastAPI 推論服務** | `shiro_api` | `http://localhost:8000/docs` | 存取 Swagger UI 或執行 `curl /health` |
| **Feast Online Redis** | `shiro_redis` | `localhost:6379` | `docker exec -it shiro_redis redis-cli ping` |
| **TimescaleDB (時序與 MLflow)** | `shiro_postgres` | `localhost:5432` | 內部容器通訊與時序 Hypertables 存取 |

---

## 4. 手動觸發 Dagster 完整訓練資產

1. 開啟瀏覽器進入 `http://localhost:3000`。
2. 進入 **Assets** 頁面，點選右上角 **Materialize All**。
3. Dagster 將依序執行：
   - `raw_taipower_load_data` (台電資料擷取並 Upsert 至 TimescaleDB)
   - `raw_weather_obs_data` (氣象觀測擷取並 Upsert 至 TimescaleDB)
   - `engineered_feature_set` → 產出 `engineered_features` / `taipower_features` / `weather_features`（後兩者經 `feast_io_manager` 發布 Parquet）
   - `trained_forecaster_model` (LightGBM 訓練並記錄於 MLflow)
   - `drift_monitoring_report` (計算 MAPE/RMSE 與漂移報告)
4. 完成後至 `http://localhost:5001` (MLflow) 即可檢視最新產出的模型參數與評估指標。

---

## 5. 停止並清理容器

```bash
make compose-down
```
