# 如何在全地端運行完整 MLOps 容器化環境

> - Created: 2026-08-23
> - Last Updated: 2026-11-24

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
- 主機需持續運行，不休眠、不關機。全台逐時實際負載只能由每 10 分鐘保存的區域供需快照推算，主機或 Docker 停機期間錯過的快照永久缺失，對應小時不計入訓練所需的有效逐時觀測。主機恢復後，各服務因 `restart: unless-stopped` 自動重啟，Dagster 排程的啟用狀態保存在 `dagster_home` volume，不需手動重新開啟。

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

拉取新程式碼後，重新執行同一指令即可重建映像並套用。

---

## 3. 服務連接埠與健康驗證

服務啟動後，各元件端點如下：

| 元件名稱 | 容器名稱 | 監聽連接埠 | 驗證方式 |
| :--- | :--- | :--- | :--- |
| **預報檢視與工程主控台** | `shiro_frontend` (Nginx) | `http://127.0.0.1:8080` | `/`、`/history` 載入預報檢視；`/console/` 載入工程主控台，重新整理 `/console/data/power/load` 仍顯示工程主控台；`/api/health` 轉送至 FastAPI 的 `/health` |
| **Dagster Webserver** | `shiro_dagster_webserver` | `http://127.0.0.1:3000` | 瀏覽器開啟檢視資產依賴圖與排程 |
| **MLflow Server** | `shiro_mlflow` | `http://127.0.0.1:5001` | 瀏覽器開啟檢視實驗指標與 Model Registry |
| **FastAPI 推論服務** | `shiro_api` | `http://127.0.0.1:8000/docs` | 直接入口的 `/health` 驗證存活、`/ready` 驗證預測就緒；互動文件僅從直接入口存取，Nginx 不提供 `/api/docs` |
| **Feast Online Redis** | `shiro_redis` | `127.0.0.1:6379` | `docker exec -it shiro_redis redis-cli ping` |
| **TimescaleDB (時序與 MLflow)** | `shiro_postgres` | `127.0.0.1:5432` | 內部容器通訊與時序 Hypertables 存取 |

所有 Compose 對主機發布的連接埠只綁定 `127.0.0.1`；容器之間仍以 Compose 服務名稱連線。前端預設 API base 為同源 `/api`，不需額外設定跨來源請求。啟動後可執行：

```bash
make frontend-smoke ARGS='--check-compose-bindings --direct-api-url http://127.0.0.1:8000'
```

輸出最後一行為 `Nginx smoke check passed` 即通過，檢查項目（兩個應用 `/` 與 `/console/`、`/published/` 匯出與 `/api`）見 [`scripts/smoke_nginx.py`](../../scripts/smoke_nginx.py)。其中 `/published/` 的兩份 JSON 要在第一次匯出後才存在；全新環境請先依第 4 節開啟 `forecast_view_export_schedule` 並待第 35 分鐘的匯出完成，或在 Dagster UI 手動 materialize `forecast_view_export`，再執行此檢查，否則會停在 `/published/latest_issued_forecast.json returned HTTP 404`。前端程式變更後，重新執行 `make compose-up` 再重新整理瀏覽器。

需要 Vite 熱重載時可使用 `make frontend`，同時啟動預報檢視（`http://127.0.0.1:5173`）與工程主控台（`http://127.0.0.1:5174/console/`）兩個開發伺服器；本機對應的前端指令見 [frontend README](../../frontend/README.md)。

修改 `frontend/nginx.conf` 或前端映像後，可在本機重現 CI 的 Nginx 檢查。此指令以獨立映像與暫時容器執行，結束後自動移除容器與網路；完整 Compose 環境已占用 8080 時，以 `FRONTEND_SMOKE_PORT` 指定其他空閒連接埠：

```bash
make frontend-smoke-ci FRONTEND_SMOKE_PORT=18080
```

輸出最後一行為 `Nginx CI smoke passed` 即與 CI 結果一致。CI 執行同一個 target，檢查內容見 [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) 與 [`scripts/ci_nginx_smoke.sh`](../../scripts/ci_nginx_smoke.sh)。

修改 `src/`、`docker/` 的 Dockerfile 或 `uv.lock` 後，可在本機重現 CI 的後端映像檢查。此指令使用獨立的 Compose 專案與 volume，結束後一併移除，不影響本機資料；但容器名稱與主機連接埠與完整環境相同，請先執行 `make compose-down`：

```bash
make backend-smoke-ci
```

輸出最後一行為 `Backend CI smoke passed` 即與 CI 結果一致；失敗時會印出所有容器的狀態與日誌。CI 執行同一個 target，檢查內容見 [`scripts/ci_backend_smoke.sh`](../../scripts/ci_backend_smoke.sh) 與 [`scripts/smoke_backend.py`](../../scripts/smoke_backend.py)。

---

## 4. 準備資料並訓練模型

`dynamic_horizon_forecast__training_job` 需要 TimescaleDB 中已有至少任務設定 `src/shiro_mlops/tasks/dynamic_horizon_forecast.toml` 的 `[policies].min_training_hours`（預設 `672`，約 28 日）個有效的全台逐時實際負載，以及時間重疊的 canonical CWA 測站觀測歷史。逐時負載只能由區域快照往後累積，無法回補；累積期間任務的訓練與監控排程會略過並揭露原因，`/ready` 應維持 HTTP 503，不應以測試 fixture 建立正式模型。開啟排程、追蹤累積進度與預期失敗邊界見 [如何在逐時負載冷啟動後恢復訓練與監控排程](recover-training-after-load-cold-start.md)。預報實績排程 `forecast_track_record_schedule` 與匯出排程 `forecast_view_export_schedule` 與擷取排程一起開啟；首次發布前每次彙整的累積天數皆為 0，匯出的最新已發布預報為空狀態，屬預期結果。匯出結果寫在 `data/published/`，由 Nginx 以 `http://127.0.0.1:8080/published/` 提供；要同時上傳到 S3，於 `.env` 設定 [預報檢視託管 §1](../reference/forecast-view-hosting.md#1-s3-配置與寫入權限) 的上傳設定，再以 `docker compose --env-file .env -f docker/docker-compose.yml up -d --force-recreate dagster-webserver` 重建容器（`restart` 不會重新讀取 `.env`）。發布排程 `issued_forecast_schedule` 則待首次訓練成功後才開啟。

1. 開啟瀏覽器進入 `http://localhost:3000`。
2. 先 materialize `raw_cwa_station_observation`，確認三個預設測站觀測已寫入 TimescaleDB。
3. materialize `raw_cwa_township_forecast`，確認三日與一週預報版本已寫入 TimescaleDB。
4. 執行 `make smoke-check ARGS="--require-ready --task dynamic_horizon_forecast"`，確認 `dynamic_horizon_forecast load accumulation` 為 `PASS` 後啟動 `dynamic_horizon_forecast__training_job`；訓練與推論只讀已入庫的 canonical tables，不會自行呼叫外部台電或 CWA API。累積不足時 `dynamic_horizon_forecast__features` 會明確失敗且不產出模型。
5. 訓練完成後執行 `docker compose -f docker/docker-compose.yml restart api`，讓 API 載入新產生的任務模型目錄 `data/models/dynamic_horizon_forecast/`（LightGBM 原生文字格式與 JSON metadata）。既有的 `data/model.joblib` 已失效且不再載入，首次重新訓練前 `/ready` 維持 `not_ready`。
6. 執行 `curl -i http://localhost:8000/ready`，確認回傳 HTTP 200 及 `normal` 或 `degraded` mode。
7. 至 `http://localhost:5001` 的 experiment `dynamic_horizon_forecast` 檢視最新模型參數與評估指標；Model Registry 的 `dynamic_horizon_forecast` 每次訓練新增一個 version。該次 run 的 Artifacts 分頁應列出 `model/` 下的模型檔；模型檔經 MLflow server 寫入 `mlflow_artifacts` volume。以舊版映像建立的 experiment 仍記著容器內的本機路徑，其後續 run 的模型檔不會出現在這裡，需要時在 MLflow UI 刪除該 experiment 後重新訓練。

在上述資料與模型尚未備妥前，`/health` 仍回傳 HTTP 200，但 `/ready` 與 `/predict` 會明確回報尚未就緒。

---

## 5. 停止並清理容器

```bash
make compose-down
```
