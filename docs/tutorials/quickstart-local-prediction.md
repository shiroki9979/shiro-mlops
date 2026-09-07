# 5 分鐘快速上手：本地隨需用電負載預測

> [!NOTE]
> **Diátaxis 象限鎖定**
>
> - **目標象限**：Tutorial
> - **目標讀者**：剛接觸專案的開發者
> - **核心目標**：在 5 分鐘內完成環境配置並取得第一次隨需負載預測結果
> - **排除內容（Avoid）**：深入的底層架構理論、雲端 Terraform 部署參數或 API 詳細字典

本教學將帶領您完成環境安裝、啟動本地 FastAPI 推論服務，並發送第一個動態視界負載預測請求。

---

## 步驟 1：安裝專案依賴

確認本機已安裝 Python 3.11+ 與 [uv](https://github.com/astral-sh/uv)。在專案根目錄執行：

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

您應該會看到全部測試通過的綠燈訊息（目前套件約收集 70+ 個離線單元／整合測試）。

---

## 步驟 4：啟動本地 API 服務

在終端機中啟動 FastAPI 開發伺服器：

```bash
uv run uvicorn shiro_mlops.service.api:app --host 0.0.0.0 --port 8000
```

終端機將顯示服務已啟動於 `http://0.0.0.0:8000`。

---

## 步驟 5：發送第一次預測請求

開啟另一個終端機視窗，使用 `curl` 請求未來 24 小時的負載預報：

```bash
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"horizon_hours": 24, "location": "Taipei"}'
```

您將收到包含未來 24 個小時預測用電負載（$MW$）與氣象預報數值的 JSON 回應：

```json
{
  "status": "success",
  "horizon_hours": 24,
  "location": "Taipei",
  "predictions": [
    {
      "datetime": "2026-08-22 00:00:00",
      "predicted_load_mw": 26850.4,
      "temperature": 28.5,
      "relative_humidity": 82.0
    }
  ]
}
```

恭喜！您已成功完成第一次端到端的用電負載預測流程。

---

## 下一步

- 若要了解 API 完整參數與型態，請參閱 [Reference: 系統規格 (SPEC.md)](../SPEC.md)。
- 若要啟動包含 Dagster 與 MLflow 的全地端容器化環境，請參閱 [How-To: 運行全地端 MLOps Stack](../how-to/run-full-local-stack.md)。
