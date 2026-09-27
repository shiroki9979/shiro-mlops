# 快速上手：本地隨需用電負載預測

- 建立日期：2026-08-23
- 最後更新：2026-09-27

> [!NOTE]
> **Diátaxis 象限鎖定**
>
> - **目標象限**：Tutorial
> - **目標讀者**：剛接觸專案的開發者
> - **核心目標**：完成本地環境配置、資料入庫與模型訓練，取得第一次隨需負載預測結果
> - **排除內容（Avoid）**：深入的底層架構理論、雲端 Terraform 部署參數或 API 詳細字典

本教學將帶領您啟動本地容器化服務、將必要資料寫入 TimescaleDB、訓練模型，並發送第一個動態視界負載預測請求。

> [!IMPORTANT]
> `dynamic_horizon_forecast__training_job` 需要資料庫中已有與台電逐時負載時間重疊的 canonical CWA 測站觀測歷史。全新空資料庫目前沒有歷史 bootstrap 指令；單次 observation materialization 可能不足以訓練模型，此時只能完成服務與資料擷取驗證，`/ready` 會維持 HTTP 503。

---

## 步驟 1：安裝專案依賴

確認本機已安裝 Python 3.11+、[uv](https://github.com/astral-sh/uv)、Docker 與 Docker Compose。在專案根目錄執行：

```bash
uv sync --all-extras
```

---

## 步驟 2：設定 CWA 授權碼

複製環境變數範本並填入中央氣象署 OpenData 授權碼；`.env` 已被 Git 忽略，不應提交實際密鑰：

```bash
cp .env.example .env
# 編輯 .env，將 CWA_API_KEY= 設為實際授權碼
```

---

## 步驟 3：執行自動化測試確認環境

執行測試套件驗證特徵工程與遞迴預測邏輯：

```bash
uv run pytest tests/ -v
```

您應該會看到全部離線單元與整合測試通過。

---

## 步驟 4：啟動本地服務

啟動 TimescaleDB、Redis、MLflow、Dagster 與 FastAPI：

```bash
make compose-up
```

確認 `curl http://localhost:8000/health` 回傳 HTTP 200。此時 process 已存活，但在資料與模型備妥前，`/ready` 與 `/predict` 仍會回傳 HTTP 503。

---

## 步驟 5：擷取資料並訓練模型

1. 開啟 `http://localhost:3000` 進入 Dagster UI。
2. materialize `raw_cwa_station_observation`。
3. materialize `raw_cwa_township_forecast`。
4. 確認已有足夠且時間重疊的 CWA 觀測歷史後，啟動 `dynamic_horizon_forecast__training_job`；此工作會讀取已入庫的台電逐時負載、訓練模型並產生任務模型目錄 `data/models/dynamic_horizon_forecast/`。若因無可用訓練列而失敗，保留 503 狀態並繼續由排程累積正式觀測資料。
5. 訓練完成後，重新啟動 API 以載入模型：

   ```bash
   docker compose -f docker/docker-compose.yml restart api
   ```

6. 確認服務已可提供預測：

   ```bash
   curl -i http://localhost:8000/ready
   ```

回應應為 HTTP 200，且 `mode` 為 `normal` 或 `degraded`。若仍回傳 503，依 `reason` 檢查模型、逐時負載或氣象涵蓋範圍。

---

## 步驟 6：在服務就緒後發送第一次預測請求

開啟另一個終端機視窗，使用 `curl` 請求未來 24 小時的負載預報：

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"horizon_hours": 24}'
```

您將收到包含未來 24 個小時預測用電負載（$MW$）與氣象預報數值的 JSON 回應；`subject` 為預測對象，全台負載固定為 `nationwide`：

```json
{
  "status": "success",
  "horizon_hours": 24,
  "subject": "nationwide",
  "mode": "normal",
  "predictions": [
    {
      "datetime": "2026-08-22 00:00:00",
      "predicted_load_mw": 26850.4,
      "temperature": 28.5,
      "relative_humidity": 82.0,
      "weather_sources": {
        "temperature": {
          "source": "three_day",
          "issued_at": "2026-08-21T23:00:00+08:00",
          "source_updated_at": "2026-08-21T23:20:00+08:00"
        },
        "relative_humidity": {
          "source": "weekly",
          "issued_at": "2026-08-21T23:00:00+08:00",
          "source_updated_at": "2026-08-21T23:25:00+08:00"
        }
      }
    }
  ]
}
```

至此已完成第一次端到端的用電負載預測流程。

---

## 下一步

- 若要了解 API 完整參數與型態，請參閱 [Reference: 系統規格 (SPEC.md)](../SPEC.md)。
- 若要啟動包含 Dagster 與 MLflow 的全地端容器化環境，請參閱 [How-To: 運行全地端 MLOps Stack](../how-to/run-full-local-stack.md)。
