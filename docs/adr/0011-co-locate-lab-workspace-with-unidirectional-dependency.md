# ADR-0011：研究空間與正式程式同庫、單向相依

> - Created: 2026-11-08
> - Last Updated: 2026-11-28
> - Author: Bo-Xue Huang
> - Status: Accepted
> - Related: [ADR-0005](0005-dependency-management-with-uv.md)、[ADR-0008](0008-derive-hourly-actual-load-from-regional-snapshots.md)、[ADR-0009](0009-decouple-ml-tasks-via-task-config-and-task-types.md)、[GLOSSARY.md](../../GLOSSARY.md)
> - Superseded by: [ADR-0018](0018-access-research-data-through-data-freezes-and-knowledge-time.md)、[ADR-0019](0019-serve-models-by-declaration-with-platform-owned-inference.md)
> - Revisions: [Notes](#5-notes)

---

## Plain Language Summary

想嘗試新的模型參數或輸入資料時，如果直接在正式程式旁邊改，既沒有統一的評估方法，也沒有地方留下可重現的研究紀錄；研究用的工具又很笨重，不該裝進正式服務。因此決定在同一個程式庫裡開一個獨立的研究空間，它可以呼叫正式程式，但正式程式不能反過來依賴它，研究用的套件也分開安裝。另外，資料庫每小時都在增加，所以研究時先把訓練資料存成一份不可覆寫的檔案，讓不同時間做的實驗能在同一份資料上比較。代價是這些檔案體積大、不進版本控制，研究報告必須記下檔案的指紋才能核對。其中「把訓練資料存成不可覆寫的檔案」這部分，已改由 [ADR-0018](0018-access-research-data-through-data-freezes-and-knowledge-time.md) 決定：研究改讀整個資料庫的凍結副本。「換一種模型做法就要另外寫一份決策紀錄」這部分，已改由 [ADR-0019](0019-serve-models-by-declaration-with-platform-owned-inference.md) 決定：新的做法通過共用的測試即可進入平台。

## 1. Context

正式程式（`src/shiro_mlops/`）只承載已定案的做法：特徵配方與模型超參數定義於各 **ML 任務**（定義見 [GLOSSARY.md](../../GLOSSARY.md)）的任務設定 TOML（[ADR-0009](0009-decouple-ml-tasks-via-task-config-and-task-types.md)），由 Dagster 排程重訓。當需要探索「現行參數或特徵配方是否可改善」時，若直接在正式程式旁隨手修改，既缺乏統一的**滾動起點回測**評估協定，也沒有地方保存可重現的研究報告與負面結論。

此外，全台逐時實際負載由區域供需快照推算、只能自開始累積起往後取得且無法回補（[ADR-0008](0008-derive-hourly-actual-load-from-regional-snapshots.md)），資料庫每小時都在變長。若無資料凍結機制，同一項研究隔兩週重跑即面對不同長度的歷史序列，候選參數之間無法在相同時間切片上公平比較。

同時，研究工作需要 `jupyterlab`、`jupytext`、`optuna`、`matplotlib` 等互動與搜尋工具，未來也可能嘗試正式環境未採用的模型家族；這些重型相依不應進入正式服務與排程環境。

## 2. Decision

在同一個儲存庫建立研究空間 `lab/`，作為 `uv` workspace 成員（延伸 [ADR-0005](0005-dependency-management-with-uv.md)），並強制單向相依：

- **同庫與單向相依（`lab` → `shiro_mlops`）**：
  - `lab/` 與 `src/` 位於同一儲存庫；`lab/` 直接呼叫 `shiro_mlops` 的公開 runner 與任務類型介面（`load_training_data`、`training_table`、`training_data_from_table`、`fit_task`、`evaluate_forecast`）。
  - `src/` 永不 import `lab`。研究結論若被採用，透過 PR 更新任務設定 TOML 的 `[params]` 並在參數旁註記研究報告出處；若共用工具被正式路徑需要，必須先搬入 `src/`。
- **`uv` Workspace 與鎖版邊界**：
  - 根目錄 `pyproject.toml` 宣告 `[tool.uv.workspace] members = ["lab"]`；`lab/pyproject.toml` 以 `{ workspace = true }` 依賴 `shiro-mlops`，放入 `jupyterlab`、`jupytext`、`optuna`、`matplotlib`、`pytest` 等研究專屬套件。
  - 根目錄 `uv sync --all-extras` 與 Dockerfile 不安裝 `lab` 的依賴；進入研究空間時以 `uv sync --package lab` 或 `uv run --package lab ...` 執行。
  - **版本一致承諾範圍**：`lab` 與根專案共用同一份 `uv.lock`，確保 `lightgbm`、`pandas`、`numpy`、`scikit-learn` 等核心套件在**使用同一份 lockfile 的環境**（本機 `uv sync`、CI）完全一致。API 與 Dagster 的 Dockerfile 以 `uv export --frozen` 從 `uv.lock` 匯出正式相依並依 hash 安裝（不含 `lab` 與 dev extras），映像檔同樣在此承諾範圍內（[#101](https://github.com/shiroki9979/shiro-mlops/issues/101) 已處理）。
- **訓練表層級的不可變快照（Snapshot）**：
  - 快照定義為指定 ML 任務在某個 `as_of`（`Asia/Taipei`）時刻的正式 `training_table` 輸出，保存於 `data/lab/snapshots/<task_id>/<as_of>.parquet`。
  - 快照只包含目標小時、預測對象、目標負載與該 ML 任務宣告的 `weather.fields` 觀測值，**不包含** lag、rolling 等衍生特徵，讓特徵配方可在讀回後作為研究變數調整。
  - `training_table` 以負載與觀測氣象時間軸的聯集無損序列化，讀回時以 `training_data_from_table` 還原為 `TrainingData`，保證經快照訓練與直接查庫訓練產出相同模型。
  - 快照寫入後不可覆寫：對已存在的 `(task_id, as_of)` 再次寫入時拋出 `FileExistsError` 並維持原檔案內容不變。
- **研究主題與治理邊界**：
  - 每個研究主題置於 `lab/<YYYY-MM-DD>-<topic>/`，以 `README.md` 記錄問題、快照（含 SHA-256）、滾動起點回測設定、基線、候選、結論與是否採用；探索筆記以 Jupytext `.py` 進版控，`*.ipynb` 列入 `.gitignore`。
  - `lab` 的 MLflow run 統一記錄於 `lab/<topic>` 前綴的 experiment，且禁止建立或修改 registered model 與 model version。
  - `lab/` 受根目錄 `ruff`、`markdownlint`、禁用詞與死連結檢查約束，但排除於正式文件的 `doc-dates` 檢查之外。

### Rationale & Alternatives Considered

- **取捨一：研究空間位置（獨立 repo vs 同庫 `lab/`）**
  - **選定方案：同庫 `lab/`，單向相依 `lab` → `shiro_mlops`**。研究程式可直接呼叫正式的 `load_training_data`、`fit_task` 與特徵管線，不會複製一份「研究版特徵轉換」造成研究與正式行為分叉；且研究報告與採用的任務設定 TOML 變更可在同一個 PR 中審閱與追溯。
  - **候選方案 A：獨立研究 repo**。隔離最徹底，但必須跨庫同步 `shiro-mlops` 版本與任務設定 TOML，極易因複製特徵邏輯或版本落差導致研究結論搬回正式環境時失真；未採納。
- **取捨二：快照粒度（原始資料表快照 vs 訓練表快照）**
  - **選定方案：凍結正式 `training_table` 輸出（不含衍生特徵）**。生產端與 Dagster `{task_id}__features` 走完全相同的最低累積門檻（`TaskNotReady`）與觀測資料選取路徑，消費端還原為 `TrainingData` 後仍可自由替換 `lags` 與 `rolling_windows` 等特徵配方。
  - **候選方案 B：匯出 `raw_taipower_load` 與 `cwa_observations` 原始表快照**。若未來研究涉及跨多氣象代表點加權或變更原始資料篩選規則時需要此層級，但對現行 ML 任務參數與特徵配方研究而言，必須在 `lab` 重建查詢與代表點對應邏輯；未採納（日後有新外生來源研究需求時再擴充）。
  - **候選方案 C：凍結已完成特徵工程的特徵矩陣（含 lag 與 rolling）**。無法在讀回快照後調整 `lags` 或 `rolling_windows` 配方；未採納。
- **取捨三：依賴隔離機制（dependency group / extra vs `uv` workspace 成員）**
  - **選定方案：`uv` workspace 成員 `lab`**。`lab` 擁有獨立的 `lab/pyproject.toml` 與 pytest 設定，根目錄 `uv sync --all-extras` 不會安裝 `optuna`、`jupyterlab` 等研究套件，同時共用根目錄 `uv.lock` 維持核心科學計算套件版本一致。
  - **候選方案 D：放在根目錄 `[project.optional-dependencies]`**。根目錄設定與 CI 的 `--all-extras` 會被迫拉入所有研究套件，把正式測試環境拖重；未採納。
  - **候選方案 E：獨立的 `lab/uv.lock`（非 workspace）**。`lab` 與根目錄各自解析依賴，`lightgbm` 或 `pandas` 版本可能漂移；未採納。
- **取捨四：採用判定的起點（同一組起點 vs 搜尋與評估分離）**
  - **選定方案：搜尋起點與評估起點分離**。超參數搜尋會挑出恰好擬合搜尋起點雜訊的候選，若在同一組起點上判定是否採用，挑選偏差會直接計入「改善幅度」而高估效益。評估起點須較晚且預報目標時段與搜尋起點不重疊，候選在評估起點上的表現才是未參與挑選的估計。代價是快照的有效起點必須切成兩組，資料不足時只能交付探索報告、不改任務設定 TOML。
  - **候選方案 F：單一起點集合同時搜尋與判定**。可用樣本較多，但挑選偏差無法扣除；未採納。具體規則見 [研究空間 §3](../reference/lab.md#3-搜尋起點與評估起點)。

## 3. Consequences

- **正面效益（Positive）**：
  - 研究與正式訓練共用同一套資料組裝、特徵轉換與模型訓練路徑，消除研究程式自行實作造成的訓練／推論偏差。
  - 不可變快照使滾動起點回測結果可在任意時間點重現，不受 `raw_taipower_load` 持續累積影響。
  - 根目錄 `uv sync --all-extras` 與正式容器映像維持輕量，不混入研究相依。
- **代價與風險（Trade-offs & Risks）**：
  - 快照檔（`.parquet`）體積較大且不進版控，研究報告必須記錄 `task_id`、`as_of` 與檔案 SHA-256 以供核對。
- **不做／延後範圍（Out of Scope / Deferred）**：
  - 自動調參的排程化 Dagster job。
  - 原始資料表層級的快照與多氣象代表點研究。
  - 更換模型家族（若研究結論建議更換模型家族，須新增任務類型、另立 ADR 並重新檢視 ADR-0003 與 ADR-0010）。

## 4. Compliance

- 單元測試：掃描 `src/` 下所有 Python 模組，不得有任何 import 指向 `lab`。
- 單元測試：`write_snapshot` 與 `read_snapshot` 經 SQLite `TaskRuntime` 往返後（含負載與觀測氣象缺口錯開的情境），還原的 `TrainingData` 與直接呼叫 `load_training_data` 相等，且 `fit_task` 訓練出的模型與直接訓練完全一致。
- 單元測試：對已存在的 `(task_id, as_of)` 再次呼叫 `write_snapshot` 必須拋出 `FileExistsError` 且原檔案內容不變；累積未達門檻時原樣拋出 `TaskNotReady`。
- CI：`lint-and-test` job 執行 `uv run --package lab pytest lab/tests`；`doc-dates` 排除 `lab/` 下的 Markdown。

## 5. Notes

- 實作追蹤：[ROADMAP M8](../ROADMAP.md)、[GitHub #89](https://github.com/shiroki9979/shiro-mlops/issues/89)（工單 [#93](https://github.com/shiroki9979/shiro-mlops/issues/93)、[#90](https://github.com/shiroki9979/shiro-mlops/issues/90)、[#91](https://github.com/shiroki9979/shiro-mlops/issues/91)、[#92](https://github.com/shiroki9979/shiro-mlops/issues/92)）。
- 部分被 [ADR-0018](0018-access-research-data-through-data-freezes-and-knowledge-time.md) 取代：§2「訓練表層級的不可變快照」、取捨二、§3 中與快照相關的效益與代價、不做範圍的「原始資料表層級的快照與多氣象代表點研究」，以及 §4 中 `write_snapshot`／`read_snapshot` 的兩條單元測試不再適用；研究改讀凍結資料，`lab/` 不再直接呼叫連線正式資料庫的 runtime。單向相依、`uv` workspace、MLflow 隔離與搜尋／評估起點分離照舊有效。
- 2026-11-28：§3 不做範圍的「更換模型家族（須新增任務類型、另立 ADR 並重新檢視 ADR-0003 與 ADR-0010）」被 [ADR-0019](0019-serve-models-by-declaration-with-platform-owned-inference.md) §2.2 取代：新任務類型以 PR 進入 `src/`，由共用的一致性測試強制，不必各立 ADR。§2 的採用路徑另由 [ADR-0020](0020-hand-off-trained-models-and-pin-the-serving-model.md) 增加交付成品一途；禁止 `lab` 寫入 MLflow registry 照舊有效。正文不動。
