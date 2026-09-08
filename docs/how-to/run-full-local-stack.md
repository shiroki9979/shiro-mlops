# 如何在全地端運行完整 MLOps 容器化環境

- 建立日期：2026-08-23
- 最後更新：2026-09-08

> [!NOTE]
> **Diátaxis 象限鎖定**
>
> - **目標象限**：How-To Guide
> - **目標讀者**：具備 Docker 與 MLOps 基本概念的工程師
> - **核心目標**：指引如何在全地端執行拓撲中啟動並驗證完整 Docker Compose MLOps Stack
> - **排除內容（Avoid）**：零基礎 Python 教學、詳細的時序演算法數學推導

本指南說明如何透過 Docker Compose 一鍵拉起包含 TimescaleDB、Redis (Feast Online Store)、MLflow Tracking Server、Dagster 與 FastAPI 的全地端工作環境。首次擷取仍需連線至台電與 CWA 外部資料來源。

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
| **FastAPI 推論服務** | `shiro_api` | `http://localhost:8000/docs` | `/health` 驗證存活；`/ready` 驗證是否可提供完整預測 |
| **Feast Online Redis** | `shiro_redis` | `localhost:6379` | `docker exec -it shiro_redis redis-cli ping` |
| **TimescaleDB (時序與 MLflow)** | `shiro_postgres` | `localhost:5432` | 內部容器通訊與時序 Hypertables 存取 |

---

## 4. 準備資料並訓練模型

`daily_training_job` 需要 TimescaleDB 中已有與台電逐時負載時間重疊的 canonical CWA 測站觀測歷史。空資料庫只 materialize 一次 observation batch 時，可能沒有足夠訓練列；目前尚無正式的歷史 bootstrap 指令，此時 `/ready` 應維持 HTTP 503，不應以測試 fixture 建立正式模型。

1. 開啟瀏覽器進入 `http://localhost:3000`。
2. 先 materialize `raw_cwa_station_observation`，確認三個預設測站觀測已寫入 TimescaleDB。
3. materialize `raw_cwa_township_forecast`，確認三日與一週預報版本已寫入 TimescaleDB。
4. 確認已有足夠且時間重疊的觀測歷史後，啟動 `daily_training_job`；訓練與推論只讀已入庫的 canonical CWA tables，不會自行呼叫外部 CWA API。
5. 訓練完成後執行 `docker compose -f docker/docker-compose.yml restart api`，讓 API 載入新產生的 `data/model.joblib`。
6. 執行 `curl -i http://localhost:8000/ready`，確認回傳 HTTP 200 及 `normal` 或 `degraded` mode。
7. 至 `http://localhost:5001` 檢視最新模型參數與評估指標。

在上述資料與模型尚未備妥前，`/health` 仍回傳 HTTP 200，但 `/ready` 與 `/predict` 會明確回報尚未就緒。

---

## 5. 停止並清理容器

```bash
make compose-down
```
