# 如何執行一次 lab 研究

- 建立日期：2026-11-09
- 最後更新：2026-11-09

> [!NOTE]
> **Diátaxis 象限鎖定**
>
> - **目標象限**：How-To Guide
> - **目標讀者**：在 `lab/` 研究工作區探索特徵配方與超參數的工程師與研究者
> - **核心目標**：完成從凍結訓練表快照、執行滾動起點回測、比較候選參數到撰寫可重現研究報告（`README.md`）與回寫 TOML 的完整流程
> - **排除內容（Avoid）**：同庫單向相依與快照架構的取捨理由（見 [ADR-0011](../adr/0011-co-locate-lab-workspace-with-unidirectional-dependency.md)）、領域名詞定義（見 [GLOSSARY.md](../../GLOSSARY.md)）

本指南說明如何在 `lab/` 研究工作區對指定 ML 任務凍結時間點快照、執行滾動起點回測，並產出符合團隊重現規範的研究報告。

---

## 1. 前置需求與環境安裝

- 已啟動地端 TimescaleDB（例如透過 [如何在全地端運行完整 MLOps 容器化環境](run-full-local-stack.md)），且目標 ML 任務已累積達最低訓練門檻（`min_training_hours`）。
- 在專案根目錄安裝 `lab` workspace 成員套件（與根目錄共用同一份 `uv.lock`）：

```bash
uv sync --package lab
```

執行 `lab` 共用工具的離線單元測試：

```bash
uv run --package lab pytest lab/tests -v
```

---

## 2. 凍結訓練表快照 (Freeze Snapshot)

研究開始前，先將指定 ML 任務在特定 `as_of`（Asia/Taipei 時間）的正式 `training_table` 凍結為不可覆寫的 Parquet 快照：

```bash
uv run --package lab python -m lab.snapshot dynamic_horizon_forecast --as-of 2026-11-08T22:00:00
```

- 產出檔案位於 `data/lab/snapshots/<task_id>/<as_of>.parquet`（例如 `data/lab/snapshots/dynamic_horizon_forecast/2026-11-08T22:00:00.parquet`）。
- 快照僅包含 `datetime`、`subject`、`load_mw` 與該任務設定的 `weather.fields`，不含 lag 或 rolling 等衍生特徵，確保特徵配方本身可作為研究變數。
- 計算並記錄快照檔案的 SHA-256 雜湊值，供研究報告引用：

```bash
sha256sum data/lab/snapshots/dynamic_horizon_forecast/2026-11-08T22:00:00.parquet
```

> [!IMPORTANT]
> 快照一經寫入即不可覆寫；對已存在的 `(task_id, as_of)` 再次執行會拋出 `FileExistsError`。

---

## 3. 讀取快照並執行滾動起點回測 (Rolling-Origin Backtest)

在研究腳本或 Jupytext `.py` 中，使用 `read_snapshot` 還原正式 `TrainingData`，並以 `rolling_origin_backtest` 評估基線與候選參數：

```python
from dataclasses import replace
import pandas as pd

from lab.backtest import rolling_origin_backtest
from lab.snapshot import read_snapshot
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task

task = deployed_task(DYNAMIC_HORIZON_FORECAST)
data = read_snapshot(task, "2026-11-08T22:00:00")

search_origins = [
    pd.Timestamp("2026-10-26 18:00:00"),
    pd.Timestamp("2026-10-27 18:00:00"),
    pd.Timestamp("2026-10-28 18:00:00"),
]
eval_origins = [
    pd.Timestamp("2026-10-29 18:00:00"),
]

# 1. 基線回測（使用現行 TOML 參數）
baseline_search = rolling_origin_backtest(task, data, origins=search_origins, horizon_hours=24)

# 2. 以 dataclasses.replace 覆寫候選參數（不修改正式 TOML）
candidate_params = task.params.model_copy(
    update={
        "lags": [1, 2, 3, 24, 48, 168],
        "rolling_windows": [6, 24, 48],
        "model": task.params.model.model_copy(
            update={"n_estimators": 150, "learning_rate": 0.03, "num_leaves": 31}
        ),
    }
)
candidate_task = replace(task, params=candidate_params)
candidate_search = rolling_origin_backtest(
    candidate_task, data, origins=search_origins, horizon_hours=24
)

# 3. 在不重疊的評估起點上比較是否贏過基線（整體 MAPE 較低即為贏）
baseline_eval = rolling_origin_backtest(task, data, origins=eval_origins, horizon_hours=24)
candidate_eval = rolling_origin_backtest(
    candidate_task, data, origins=eval_origins, horizon_hours=24
)
is_adopted = candidate_eval.beats(baseline_eval)
```

### 起點有效性與分離原則

1. **三項有效性檢查**：每個起點 `origin` 必須同時滿足：
   - `datetime <= origin` 的有效實際負載小時數達 `min_history_hours`（預設取任務設定 `policies.min_training_hours`）；
   - `(origin - lookback_hours, origin]` 的逐時負載完整無缺漏（含 `origin` 當小時）；
   - `origin + 1h .. origin + horizon_hours` 的實際負載與經 2 小時向後對齊後的觀測氣象皆完整無缺值。
2. **搜尋起點與評估起點分離**：超參數搜尋（例如 Optuna objective）只能在「搜尋起點」上計算整體 MAPE；是否採用候選參數則只在較晚、且預報目標時段與任何搜尋起點目標時段不重疊的「評估起點」上判定。若快照的有效起點跨度不足以切出具備代表性的評估起點，研究僅交付探索報告，不修改正式 TOML。
3. **MLflow 紀錄隔離**：研究過程若記錄 MLflow run，experiment 名稱須使用 `lab/<topic>` 前綴（例如 `lab/dhf-hyperparameter-search`），且**嚴禁**建立或寫入任何 registered model 或 model version。

---

## 4. 建立研究主題目錄與撰寫報告 (`README.md`)

每個研究主題存放於 `lab/<YYYY-MM-DD>-<topic>/`（例如 [`lab/2026-11-08-dhf-hyperparameter-search/README.md`](../../lab/2026-11-08-dhf-hyperparameter-search/README.md)）：

- 互動式探索以 Jupytext 配對 `.py`（`percent` 格式）與 `.ipynb`；**只有 `.py` 與 `README.md` 進版控**，`*.ipynb` 已由 `.gitignore` 排除。
- 引用 `data/lab/snapshots/...` 或 `*.ipynb` 等不進版控的路徑時，一律使用 code span（例如 `` `data/lab/snapshots/...` ``），不可使用 Markdown 連結，以免觸發 CI 死連結檢查失敗。

### 4.1 報告 `README.md` 的固定段落

每份 `lab/<YYYY-MM-DD>-<topic>/README.md` 必須依序包含以下七個固定段落：

1. **問題 (Problem)**：研究要回答的具體問題與評估標的。
2. **快照 (Snapshot)**：使用的快照檔案資訊、雜湊值與連續區間查核。
3. **回測設定 (Backtest Settings)**：回測視界、最低累積門檻、搜尋起點與評估起點清單，以及「**使用觀測氣象的條件式回測結果，不代表正式 serving 誤差**」聲明。
4. **基線 (Baseline)**：現行 TOML 參數在搜尋起點與評估起點上的整體 MAPE 及 `1..horizon_hours` 各提前時數分組 MAPE。
5. **候選 (Candidates)**：搜尋空間、試驗設定與最佳候選參數在各分組上的回測表現。
6. **結論 (Conclusion)**：基線與候選在搜尋起點及評估起點上的比較分析。
7. **是否採用 (Adoption Decision)**：明確記載是否採用至正式任務設定 TOML；若採用，於 TOML 參數旁加上註解連回本報告。

### 4.2 必備重現紀錄欄位檢查表

為確保不依賴 MLflow 服務也能完整重現實驗，報告內必須包含下表所有欄位：

| 重現紀錄欄位 | 說明與範例 |
| :--- | :--- |
| **Git revision** | 執行回測時的 commit SHA（例如 `b343382`） |
| **快照識別與 SHA-256** | `task_id`、`as_of`、code span 路徑與完整檔案 SHA-256 |
| **任務設定來源與完整基線參數** | 來源 TOML 路徑，以及 `lags`、`rolling_windows`、`model.*` 完整參數值 |
| **完整候選參數** | 最佳候選的 `lags`、`rolling_windows`、`model.*` 完整參數值 |
| **搜尋起點與評估起點清單** | 兩組起點的完整 ISO 時間戳記與不重疊說明 |
| **預報視界 (`horizon_hours`)** | 例如 `24` |
| **最低歷史累積 (`min_history_hours`)** | 數值、是否覆寫（`min_history_overridden`），若覆寫須載明理由 |
| **Optuna 搜尋設定** | 搜尋空間各維度範圍、亂數 `seed`、總 `trial` 數 |
| **分組誤差揭露** | 搜尋與評估起點上 `1..horizon_hours` 各提前時數分組 MAPE |
