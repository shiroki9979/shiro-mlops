# 研究空間（`lab/`）介面與報告契約

- 建立日期：2026-11-20
- 最後更新：2026-11-21
- 專案版本：`0.4.0`

> 由 `docs/SPEC.md` 第 7 節拆出。

---

> 依 [ADR-0011](../adr/0011-co-locate-lab-workspace-with-unidirectional-dependency.md)。程式位於 `lab/`，相依方向固定為 `lab` → `shiro_mlops`；操作步驟見 [如何執行一次 lab 研究](../how-to/run-lab-study.md)。

## 1. 快照（`lab/snapshot.py`）

| 介面 | 行為 |
| :--- | :--- |
| `write_snapshot(task, runtime, as_of, *, variant=None, snapshots_dir) -> Path` | 以 `load_training_data` + `training_table` 凍結訓練表，並於 parquet 記錄 `task.weather` 的代表點、權重與欄位；目標檔已存在時拋 `FileExistsError` 且不改動原檔；`TaskNotReady` 原樣拋出 |
| `read_snapshot(task, as_of, *, variant=None, snapshots_dir) -> TrainingData` | 讀回 parquet 後以 `training_data_from_table` 還原；快照記錄的天氣與 `task.weather` 不同時拋 `SnapshotWeatherMismatchError`；未記錄天氣的舊快照不檢查 |
| `snapshot_path(task, as_of, *, variant=None, snapshots_dir) -> Path` | 無 `variant` 時回傳 `<snapshots_dir>/<task_id>/<as_of>.parquet`，有 `variant` 時回傳 `<snapshots_dir>/<task_id>/<variant>/<as_of>.parquet`；`variant` 限小寫英數與連字號，否則拋 `ValueError`；`as_of` 一律換算為 Asia/Taipei 無時區時間 |

訓練表只保存加權天氣（[ADR-0012](../adr/0012-combine-weather-reference-points-into-weighted-weather.md)），代表點或權重不同的候選須各自凍結快照，以 `variant` 區分；放假日等 `[params]` 差異可共用同一份快照。

`snapshots_dir` 預設 `data/lab/snapshots`（不進版控）。CLI：`uv run --package lab python -m lab.snapshot <task_id> --as-of <ISO> [--variant <name> --reference-points <alias>... --weights <w>...]`；`--reference-points` 取代任務設定的代表點並沿用其 `weather.fields`，驗證規則與任務設定相同（`build_weather_spec`），且必須搭配 `--variant`。

## 1.1 代表點權重（`lab/regional_weights.py`）

`regional_load_shares(snapshots, *, start, end) -> RegionalLoadShares` 以區域供需快照計算 `source_time` 落在 `[start, end)` 的北中南東用電占比，供 TICKET-303 推算氣象代表點權重。

- **有效樣本**：與逐時實際負載推算相同（`complete_region_loads`）：四區齊全的 `source_time` 才計入，同一 `source_time` 多次擷取只算一次。期間內沒有有效樣本時拋 `ValueError`。
- **占比**：各區在有效樣本的用電加總除以四區總和。
- **權重**：`reference_point_weights(region_points=REGION_REFERENCE_POINTS, *, decimals=None)` 將北部、中部、南部對應臺北、臺中、高雄；東部占比依三點比例分配，等同三區占比重新正規化。指定 `decimals` 時逐一四捨五入，差額歸給最大權重，使總和恰為 1。

CLI：`uv run --package lab python -m lab.regional_weights --start <ISO> --end <ISO> [--decimals 3]`，輸出期間、有效樣本數、四區占比、權重，以及可直接傳給 `lab.snapshot` 的 `--reference-points`／`--weights` 參數。

## 2. 滾動起點回測（`lab/backtest.py`）

`rolling_origin_backtest(task, data, origins, horizon_hours, *, min_history_hours=None) -> BacktestReport` 為純函式，不做 I/O。

- **起點語意**：起點為最後一筆已知實際負載的整點，預報目標為 `origin + 1h .. origin + horizon_hours`（`target_hours(origin, horizon_hours)`）。
- **訓練**：負載與氣象皆截斷為 `datetime <= origin`，`validation_start = origin + 1h`（驗證集為空）。
- **預報**：`PredictionData.anchor = origin`，`load_history` 含起點當小時；`weather` 為目標時段的完整逐時軸，以正式的觀測氣象對齊規則（2 小時內向後對齊）填入。
- **起點有效性**：每個起點須同時滿足下列條件，任一不合格拋 `ValueError` 並指出起點與條件：
  1. `datetime <= origin` 的有效負載小時數達 `min_history_hours`（預設取任務設定 `policies.min_training_hours`）。
  2. `(origin - lookback_hours, origin]` 的逐時負載完整（含起點當小時）。serving 以相同條件拒絕預測（[ML 任務設定 §2](ml-tasks.md#2-任務類型介面taskstypes)），回測與 serving 接受的起點一致。
  3. 目標時段的實際負載與對齊後觀測氣象皆有值。

`BacktestReport` 欄位：

| 欄位 | 說明 |
| :--- | :--- |
| `overall_mape` | 所有起點、所有提前時數合併的 MAPE（`evaluate_forecast`） |
| `mape_by_horizon` | 提前時數 `1..horizon_hours` 各自的 MAPE |
| `predictions` | 每個起點的預報值序列（依提前時數排序） |
| `origins`、`horizon_hours` | 正規化後的起點清單與視界 |
| `min_history_hours`、`min_history_overridden` | 實際使用的最低累積與是否由呼叫端覆寫 |
| `params` | 所用任務參數 |

起點盤點（不訓練模型）：

| 介面 | 行為 |
| :--- | :--- |
| `eligible_origins(task, data, horizon_hours, *, min_history_hours=None)` | 以上述三項起點有效性條件逐一檢查快照內每個整點，回傳 `rolling_origin_backtest` 會接受的全部起點 |
| `origin_runs(origins)` | 將排序後的起點分組為連續整點區間 `(first, last)` |
| `split_search_and_eval_origins(eligible, *, horizon_hours, eval_calendar_days, hour_step)` | 只取整點為 `hour_step` 倍數的起點；最後 `eval_calendar_days` 個日曆日為評估起點，搜尋起點為 `<= 第一個評估起點 - horizon_hours` 者，並以 `verify_non_overlapping_target_windows` 驗證；沒有可用的評估或搜尋起點時拋 `ValueError` |
| `training_row_count(task, data, origin)` | 遞迴回歸任務在 `origin` 截斷後實際訓練的列數（缺任一 lag 或天氣的列已剔除），用於揭露加權天氣嚴格缺值的訓練列損失 |

CLI：`uv run --package lab python -m lab.origins <task_id> --as-of <ISO> [--variant <name> --reference-points ... --weights ...] [--horizon-hours 24] [--eval-days 7] [--hour-step 6]`，輸出合格起點數、日曆日數、連續區間、建議的搜尋／評估切分，以及評估起點是否涵蓋 `--eval-days` 個日曆日（`sufficient: yes|no`）。

`candidate.beats(baseline)`：起點清單與視界相同時，`overall_mape` 嚴格較低即為贏；起點或視界不同時拋 `ValueError`。回測使用觀測氣象，結果為「氣象已知」條件下的條件式數字，不代表正式 serving 誤差，也不是其上界或下界。

## 3. 搜尋起點與評估起點

- 超參數搜尋的 objective 只在搜尋起點上計算整體 MAPE；是否採用只比較基線與最佳候選在評估起點上的 `BacktestReport`。
- `verify_non_overlapping_target_windows(search_origins, eval_origins, horizon_hours)`：評估起點須全部晚於搜尋起點，且兩組的目標時段不得有任何共同小時；違反時拋 `ValueError`。
- 評估起點不足以代表負載型態時（門檻由研究主題定義並寫入報告），只交付探索報告，不修改任務設定 TOML。

## 4. MLflow 隔離

lab 的 run 記錄於 experiment `lab/<topic>`；不得呼叫 model registry 的任何寫入操作。MLflow 不可用時記錄警告並繼續。

## 5. 研究報告（`lab/<YYYY-MM-DD>-<topic>/README.md`）

固定段落依序為：問題、快照、回測設定、基線、候選、結論、是否採用。回測設定段須含觀測氣象條件式聲明（§2）。採用時在任務設定 TOML 參數旁註解連回報告。

重現紀錄欄位（不依賴 MLflow 可用）：

| 欄位 | 內容 |
| :--- | :--- |
| Git revision | 產生報告數字的 commit SHA |
| 快照 | `task_id`、`as_of`、code span 路徑、檔案 SHA-256 |
| 基線參數 | 任務設定 TOML 路徑與完整 `[params]` |
| 候選參數 | 最佳候選完整參數 |
| 起點 | 搜尋起點與評估起點完整清單 |
| 視界 | `horizon_hours` |
| 最低累積 | `min_history_hours`、是否覆寫與理由 |
| 搜尋設定 | 搜尋空間、seed、trial 數 |
| 分組誤差 | 搜尋與評估起點的 `1..horizon_hours` 各分組 MAPE |

不進版控的路徑（快照、`*.ipynb`）以 code span 引用，不用 Markdown 連結。
