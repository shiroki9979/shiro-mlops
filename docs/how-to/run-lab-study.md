# 如何執行一次 lab 研究

> - Created: 2026-11-09
> - Last Updated: 2026-11-24

在 `lab/` 研究工作區探索特徵配方與超參數的工程師與研究者，可依本指南對指定 ML 任務走完從凍結時間點訓練表快照、執行滾動起點回測、比較候選參數，到撰寫符合團隊重現規範的研究報告（`README.md`）並回寫 TOML 的完整流程。同庫單向相依與快照架構的取捨理由見 [ADR-0011](../adr/0011-co-locate-lab-workspace-with-unidirectional-dependency.md)，領域名詞定義見 [GLOSSARY.md](../../GLOSSARY.md)，本指南不重複說明。

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

### 比較不同氣象代表點或權重時

訓練表只保存加權後的天氣，代表點或權重不同的候選須各自凍結一份快照；只改 `[params]`（例如放假日開關）的候選可共用同一份。

1. 以區域供需快照推算權重，期間採半開區間 `[start, end)`：

   ```bash
   uv run --package lab python -m lab.regional_weights --start 2026-10-01T00:00:00 --end 2026-11-01T00:00:00
   ```

   輸出最後一行為 `snapshot arguments: --reference-points Taipei Taichung Kaohsiung --weights ...`，將期間、有效樣本數與權重記入研究報告。

2. 以相同 `as_of` 凍結候選快照，並以 `--variant` 命名，貼上第 1 步輸出的參數：

   ```bash
   uv run --package lab python -m lab.snapshot dynamic_horizon_forecast --as-of 2026-11-08T22:00:00 --variant three-point --reference-points Taipei Taichung Kaohsiung --weights 0.5 0.3 0.2
   ```

   產出檔案位於 `data/lab/snapshots/<task_id>/<variant>/<as_of>.parquet`，不影響同一 `as_of` 的基線快照。

3. 研究腳本以相同天氣讀回快照；天氣與快照記錄不一致時，`read_snapshot` 會拋出 `SnapshotWeatherMismatchError`：

   ```python
   from dataclasses import replace

   from lab.snapshot import read_snapshot
   from shiro_mlops.core.config import settings
   from shiro_mlops.tasks.definition import build_weather_spec

   weighted_task = replace(
       task,
       weather=build_weather_spec(
           ["Taipei", "Taichung", "Kaohsiung"],
           [0.5, 0.3, 0.2],
           task.weather.fields,
           settings.cwa_locations,
       ),
   )
   weighted_data = read_snapshot(weighted_task, "2026-11-08T22:00:00", variant="three-point")
   ```

三點加權只在各點同一整點皆有觀測時才有值，候選快照的訓練列數可能少於基線；比較候選時一併記錄各快照的列數。

---

## 3. 確認快照提供的起點

選擇起點前，先列出快照中每個能通過起點有效性檢查的整點，並確認評估起點能否涵蓋 7 個日曆日：

```bash
uv run --package lab python -m lab.origins dynamic_horizon_forecast --as-of 2026-11-08T22:00:00
```

- `run:` 各行為合格起點的連續區間；區間之間的空缺來自負載或觀測氣象缺口。
- `search origins:`／`eval origins:` 為建議切分；`sufficient: no` 表示評估起點不足，該快照只能產出探索報告。
- 天氣候選的快照加上與凍結時相同的 `--variant`、`--reference-points` 與 `--weights`；三點加權的合格起點可能比基線少，研究應使用各候選合格起點的交集。

## 4. 讀取快照並執行滾動起點回測 (Rolling-Origin Backtest)

在研究腳本或 Jupytext `.py` 中，使用 `read_snapshot` 還原正式 `TrainingData`，並以 `rolling_origin_backtest` 評估基線與候選參數：

```python
from dataclasses import replace
import pandas as pd

from lab.backtest import rolling_origin_backtest, verify_non_overlapping_target_windows
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
# 評估起點須晚於搜尋起點且目標時段不重疊，否則拋出 ValueError
verify_non_overlapping_target_windows(search_origins, eval_origins, horizon_hours=24)

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

起點與報告欄位的完整規則見 [研究空間介面與報告契約](../reference/lab.md)；以下只列操作時的檢查步驟：

1. 先以基線參數對兩組起點各跑一次回測；若拋出 `ValueError`，訊息會指出不合格的起點與條件，改選連續無缺口區間內的起點。
2. 研究過程若記錄 MLflow run，experiment 名稱使用 `lab/<topic>`，不寫入 model registry。

---

## 5. 建立研究主題目錄與撰寫報告 (`README.md`)

每個研究主題存放於 `lab/<YYYY-MM-DD>-<topic>/`（例如 [`lab/2026-11-08-dhf-hyperparameter-search/README.md`](../../lab/2026-11-08-dhf-hyperparameter-search/README.md)）：

1. 建立 `lab/<YYYY-MM-DD>-<topic>/`，研究腳本以 Jupytext `percent` 格式撰寫，標頭宣告 `formats: ipynb,py:percent`。
2. 需要互動探索時產生配對 notebook（`*.ipynb` 由 `.gitignore` 排除，只有 `.py` 與 `README.md` 進版控）：

   ```bash
   uv run --package lab jupytext --sync lab/<YYYY-MM-DD>-<topic>/<script>.py
   ```

3. 程式變更全部 commit 後，在該 commit 上執行研究腳本，報告中的數字必須來自這次執行。
4. 依 [研究空間 §5](../reference/lab.md#5-研究報告labyyyy-mm-dd-topicreadmemd) 的固定段落與重現紀錄欄位撰寫 `README.md`，Git revision 填第 3 步的 commit SHA。
5. 引用 `data/lab/snapshots/...` 或 `*.ipynb` 等不進版控的路徑時使用 code span，不用 Markdown 連結，否則 CI 死連結檢查會失敗。
6. 若結論為採用，在同一個 PR 更新任務設定 TOML 的 `[params]`，並在參數旁加註解連回報告。
