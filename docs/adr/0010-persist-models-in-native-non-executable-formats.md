# ADR-0010：模型以原生非執行格式保存

> - Created: 2026-09-27
> - Last Updated: 2026-11-27
> - Author: Bo-Xue Huang
> - Status: Accepted
> - Related: [ADR-0009](0009-decouple-ml-tasks-via-task-config-and-task-types.md)、[資料契約 §5 Dagster Artifact 序列化與信任邊界](../reference/data-contracts.md#5-dagster-artifact-序列化與信任邊界)

---

## Plain Language Summary

訓練好的模型原本用 Python 的通用序列化格式（pickle）存檔，這種格式在讀檔時可以執行任意程式，等於把模型檔當成可信任的程式碼。專案的其他資料檔早已禁止這種格式，只有模型檔例外。因此決定禁止用這類格式保存或讀取模型，改用各模型自己的純資料格式：樹狀模型存成它原生的文字檔，神經網路只存權重數值與參數。代價是神經網路的計算要由專案自己實作並用測試核對，可用的網路結構因此受限；舊的模型檔也不能再讀，必須重新訓練。

## 1. Context

模型以 joblib（底層為 pickle）保存於 `DATA_DIR/model.joblib`，API 啟動時直接反序列化。SPEC 1.5 已將 local `DATA_DIR` 與 S3 視為非信任位元組，並禁止 Dagster artifact 以 pickle 反序列化，模型檔卻不受此約束，形成信任邊界不一致。ADR-0009 引入多個模型家族（LightGBM 回歸與分類、sklearn MLP AutoEncoder），保存方式須由任務類型統一負責，不一致面會隨任務數擴大。

## 2. Decision

- 模型保存與載入屬於任務類型介面；平台只依 `task_id` 分配模型目錄。
- 禁止以 pickle 或 joblib 保存、載入模型。
- **LightGBM**（回歸與分類）：使用 Booster 原生文字格式。
- **sklearn MLP AutoEncoder**：權重、偏差與縮放參數存為 `.npz`（`allow_pickle=False`），超參數與特徵名稱存為 JSON；推論使用本專案的 numpy 前向計算。訓練時限定隱藏層 `relu`、輸出層 `identity`。
- 既有 `model.joblib` 不提供相容載入，須重新訓練產生新格式，與 SPEC 1.5 對舊 pickle artifact 的遷移策略一致。

### Rationale & Alternatives Considered

- **選定方案：各模型家族的原生非執行格式**。讀取模型檔不具執行任意程式碼的能力；不新增相依；文字格式與 JSON 可人工檢視。
- **候選方案 A：沿用 joblib，信任邊界另案處理**。改動最少，但多模型家族會擴大不一致面；未採納。
- **候選方案 B：skops**。sklearn 專用安全格式，以型別白名單載入；未採納，因需新增相依，且 LightGBM 仍需另一套格式。
- **候選方案 C：ONNX**。可跨語言，但需 skl2onnx 與 onnxruntime 兩個大型相依，跨語言推論並非需求。
- **候選方案 D：MLflow model flavors**。sklearn flavor 底層仍為 pickle 或 cloudpickle，未解決信任問題。

## 3. Consequences

- **正面效益（Positive）**：模型檔與 Dagster artifact 採用一致的信任邊界；模型檔可人工檢視與比對。
- **代價與風險（Trade-offs & Risks）**：
  - AutoEncoder 前向計算由本專案維護，須以測試對齊 sklearn；MLP 設定彈性受限於已支援的激活函數。
  - 既有 `model.joblib`（2026-09-03，以舊口徑資料訓練）失效。全台逐時實際負載約於 2026-10-24 累積滿 28 日，首次重新訓練前 `/ready` 維持 not_ready，`/predict` 回傳 503。
- **不做／延後範圍（Out of Scope / Deferred）**：模型檔簽章或完整性雜湊；改由 MLflow registry 載入模型。

## 4. Compliance

- 單元測試：numpy 前向計算與 `MLPRegressor.predict` 在固定 fixture 上的輸出於容差內一致。
- 單元測試：各任務類型保存後再載入，預測結果與保存前一致。
- 單元測試：掃描 `src/`，不得 import `joblib` 或 `pickle`。
- `np.load` 呼叫一律明示 `allow_pickle=False`，納入 Code Review 清單。

## 5. Notes

- 實作併入 ROADMAP M7 的任務類型介面切片（[GitHub #66](https://github.com/shiroki9979/shiro-mlops/issues/66)，見 ADR-0009）。
