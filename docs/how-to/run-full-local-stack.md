# 如何在全地端運行完整 MLOps 容器化環境

- 建立日期：2026-08-23
- 最後更新：2026-10-25

> [!NOTE]
> **Diátaxis 象限鎖定**
>
> - **目標象限**：How-To Guide
> - **目標讀者**：具備 Docker 與 MLOps 基本概念的工程師
> - **核心目標**：指引如何在全地端執行拓撲中啟動並驗證完整 Docker Compose MLOps Stack
> - **排除內容（Avoid）**：零基礎 Python 教學、詳細的時序演算法數學推導

本指南說明如何透過 Docker Compose 一鍵啟動 Nginx 前端預覽、FastAPI、TimescaleDB、Redis (Feast Online Store)、MLflow Tracking Server 與 Dagster 的全地端工作環境。首次擷取仍需連線至台電與 CWA 外部資料來源。Nginx 提供 Docker 建置後的靜態前端，不提供熱重載；雲端前端部署不在此流程內。

---

## 1. 前置需求

- 已安裝 Docker 與 Docker Compose (v2.0+)
- 本機可用記憶體建議 $\ge 4 \text{ GB}$

---

## 2. 啟動所有服務

先在專案根目錄準備本機環境變數，並填入 `CWA_API_KEY`；`.env` 已被 Git 忽略。啟動時必須讓 Compose 讀到這個檔案，否則 CWA 入庫會因空授權碼回 401：

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
docker compose --env-file .env -f docker/docker-compose.yml up -d
```

---

## 3. 服務連接埠與健康驗證

服務啟動後，各元件端點如下：

| 元件名稱 | 容器名稱 | 監聽連接埠 | 驗證方式 |
| :--- | :--- | :--- | :--- |
| **React 視覺化儀表板** | `shiro_frontend` (Nginx) | `http://127.0.0.1:8080` | 載入已建置的 SPA；`/api/health` 轉送至 FastAPI 的 `/health`；重新整理 `/data/power/load` 仍顯示 SPA |
| **Dagster Webserver** | `shiro_dagster_webserver` | `http://127.0.0.1:3000` | 瀏覽器開啟檢視資產依賴圖與排程 |
| **MLflow Server** | `shiro_mlflow` | `http://127.0.0.1:5001` | 瀏覽器開啟檢視實驗指標與 Model Registry |
| **FastAPI 推論服務** | `shiro_api` | `http://127.0.0.1:8000/docs` | 直接入口的 `/health` 驗證存活、`/ready` 驗證預測就緒；互動文件僅從直接入口存取，Nginx 不提供 `/api/docs` |
| **Feast Online Redis** | `shiro_redis` | `127.0.0.1:6379` | `docker exec -it shiro_redis redis-cli ping` |
| **TimescaleDB (時序與 MLflow)** | `shiro_postgres` | `127.0.0.1:5432` | 內部容器通訊與時序 Hypertables 存取 |

所有 Compose 對主機發布的連接埠只綁定 `127.0.0.1`；容器之間仍以 Compose 服務名稱連線。前端預設 API base 為同源 `/api`，不需額外設定跨來源請求。啟動後可執行：

```bash
make frontend-smoke ARGS='--check-compose-bindings --direct-api-url http://127.0.0.1:8000'
```

此檢查會經 Nginx 驗證首頁、深層路由、建置資產、遺失資產的 404 與 `/api/health`，並確認 API 直接入口及 Compose 主機埠綁定。前端程式變更後，從專案根目錄重新建置靜態映像，再重新整理瀏覽器：

```bash
docker compose --env-file .env -f docker/docker-compose.yml up -d --build frontend
```

需要 Vite 熱重載時仍可使用 `make frontend`，由 `http://127.0.0.1:5173` 開啟開發伺服器。CI 重用同一支 `make frontend-smoke` 腳本，檢查項目見 [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)；本機對應的前端指令見 [frontend README](../../frontend/README.md)。

---

## 4. 準備資料並訓練模型

`dynamic_horizon_forecast__training_job` 需要 TimescaleDB 中已有至少任務設定 `src/shiro_mlops/tasks/dynamic_horizon_forecast.toml` 的 `[policies].min_training_hours`（預設 `672`，約 28 日）個有效的全台逐時實際負載，以及時間重疊的 canonical CWA 測站觀測歷史。逐時負載只能由區域快照往後累積，無法回補；累積期間任務的訓練與監控排程會略過並揭露原因，`/ready` 應維持 HTTP 503，不應以測試 fixture 建立正式模型。開啟排程、追蹤累積進度與預期失敗邊界見 [如何在逐時負載冷啟動後恢復訓練與監控排程](recover-training-after-load-cold-start.md)。

1. 開啟瀏覽器進入 `http://localhost:3000`。
2. 先 materialize `raw_cwa_station_observation`，確認三個預設測站觀測已寫入 TimescaleDB。
3. materialize `raw_cwa_township_forecast`，確認三日與一週預報版本已寫入 TimescaleDB。
4. 執行 `make smoke-check ARGS=--require-ready`，確認 `dynamic_horizon_forecast load accumulation` 為 `PASS` 後啟動 `dynamic_horizon_forecast__training_job`；訓練與推論只讀已入庫的 canonical tables，不會自行呼叫外部台電或 CWA API。累積不足時 `dynamic_horizon_forecast__features` 會明確失敗且不產出模型。
5. 訓練完成後執行 `docker compose -f docker/docker-compose.yml restart api`，讓 API 載入新產生的任務模型目錄 `data/models/dynamic_horizon_forecast/`（LightGBM 原生文字格式與 JSON metadata）。既有的 `data/model.joblib` 已失效且不再載入，首次重新訓練前 `/ready` 維持 `not_ready`。
6. 執行 `curl -i http://localhost:8000/ready`，確認回傳 HTTP 200 及 `normal` 或 `degraded` mode。
7. 至 `http://localhost:5001` 的 experiment `dynamic_horizon_forecast` 檢視最新模型參數與評估指標；Model Registry 的 `dynamic_horizon_forecast` 每次訓練新增一個 version。

在上述資料與模型尚未備妥前，`/health` 仍回傳 HTTP 200，但 `/ready` 與 `/predict` 會明確回報尚未就緒。

---

## 5. 停止並清理容器

```bash
make compose-down
```
