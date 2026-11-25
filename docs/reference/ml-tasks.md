# ML 任務設定與任務類型介面

> - Created: 2026-11-20
> - Last Updated: 2026-11-24

---

> 依 [ADR-0009](../adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md) 與 [ADR-0010](../adr/0010-persist-models-in-native-non-executable-formats.md)。程式位於 `src/shiro_mlops/tasks/`，任務設定檔與程式一同隨映像檔發布。

## 1. 任務設定 Schema（`tasks/<task_id>.toml`）

以標準函式庫 `tomllib` 讀取，兩階段 Pydantic 驗證：先驗證共通欄位，再以任務類型的 `params_model` 驗證 `[params]`、`health_model` 驗證 `[health]`。Dagster code location 載入與 API 啟動時即載入全部任務設定；任何錯誤皆拋出 `TaskDefinitionError(path, detail)`，`detail` 指出欄位路徑（如 `policies.stale_anchor_max_lag_hours`、`params.rolling_windows`）。未知欄位一律拒絕。

| 欄位 | 型別 | 規則 |
| :--- | :--- | :--- |
| `task_id` | string | 小寫英數與底線；必須等於檔名（不含 `.toml`） |
| `task_type` | string | 必須為已註冊的任務類型（§2） |
| `subject` | string | 預測對象識別碼，例如 `nationwide` |
| `target` | `"hourly_actual_load"` | 目標序列來源；目前只有全台逐時實際負載（`raw_taipower_load`，`source = 'regional_snapshot_sum'`） |
| `weather.reference_points` | list[string] | 必須引用 CWA 擷取目錄中的 alias，不得重複 |
| `weather.weights` | list[float] | 與 `reference_points` 一一對應的權重，每個大於 0、總和為 1（容許 `1e-6` 浮點誤差）；只有一個代表點時可省略（權重為 1），多個代表點時必填 |
| `weather.fields` | list[`temperature` \| `relative_humidity`] | 訓練觀測與預報皆提供的氣象欄位，不得重複；可只列其中一個 |
| `policies.min_training_hours` | 正整數 | 最低累積門檻（[Dagster 排程](dagster-schedules.md)的「最低累積」） |
| `policies.stale_anchor_max_lag_hours` | 正整數 | 負載起點過舊門檻（[REST API §2](rest-api.md#2-就緒狀態檢查)） |
| `policies.validation_fraction` | 0 < x < 1 | 依時間切分的驗證比例 |
| `params` | table | 依任務類型驗證；為特徵配方與模型超參數的唯一來源 |
| `schedule.training` | cron string | 訓練排程（`Asia/Taipei`，[Dagster 排程](dagster-schedules.md)）；五個欄位，只接受數字、`*`、範圍、步進與逗號清單，超出欄位範圍即拒絕 |
| `schedule.monitoring` | cron string | 監控排程（`Asia/Taipei`，[Dagster 排程](dagster-schedules.md)）；規則同上 |
| `health` | table | 依任務類型的 `health_model` 驗證；健康判定門檻的唯一來源 |

`recursive_regression` 的 `[params]`：`lags`（正整數 list，至少一個）、`rolling_windows`（正整數 list，至少一個）、`day_off`（布林，預設 `false`；開啟時加入以各小時日期判定的 `is_day_off`）、`[params.model]` 的 `n_estimators`（正整數）、`learning_rate`（正數）、`num_leaves`（≥ 2）；objective、metric 與 random seed 由任務類型固定。`[health]`：`max_mape`（正數，單位 %）。

`direct_classification` 的 `[params]`：`lags`、`rolling_windows`（規則同上，但皆相對於錨點）、`day_off`（布林，預設 `false`；開啟時加入以目標小時日期判定的 `is_day_off`）、`[params.threshold]` 的 `window_days`（正整數）與 `quantile`（0 < x < 1）、`[params.model]`（同上）；objective（`binary`）與 random seed 由任務類型固定。`[health]`：`min_precision`、`min_recall`、`min_f1`（皆為 0–1）。

`unsupervised_reconstruction` 的 `[params]`：`window_hours`（整數 ≥ 6，時間窗長度）、`threshold_quantile`（0 < x < 1，判定門檻取驗證期校準日重建誤差的分位數）、`[params.model]` 的 `hidden_layer_sizes`（一至三個正整數，淺層）、`alpha`（≥ 0）、`learning_rate_init`（正數）、`max_iter`（正整數）；激活函數（隱藏層 `relu`、輸出層 `identity`）、solver `adam` 與 random seed 由任務類型固定。`[health]`：`min_recall`（0 < x ≤ 1）、`max_false_positive_rate`（0 ≤ x < 1）。

動態視界預報任務設定 `tasks/dynamic_horizon_forecast.toml`：`subject = "nationwide"`、氣象代表點 `Taipei`、`min_training_hours = 672`、`stale_anchor_max_lag_hours = 3`、`validation_fraction = 0.2`、`lags = [1, 2, 24, 48, 168]`、`rolling_windows = [6, 24]`、LightGBM `n_estimators = 100`、`learning_rate = 0.05`、`num_leaves = 31`、`[schedule]` `training = "0 0 * * *"`／`monitoring = "0 * * * *"`、`[health]` `max_mape = 10.0`。

高負載預警任務設定 `tasks/high_load_alert.toml`：`task_type = "direct_classification"`、`subject = "nationwide"`、氣象代表點 `Taipei`、`min_training_hours = 1344`、`stale_anchor_max_lag_hours = 3`、`validation_fraction = 0.2`、`lags = [1, 2, 24, 168]`、`rolling_windows = [6, 24]`、`threshold.window_days = 28`、`threshold.quantile = 0.9`、LightGBM `n_estimators = 200`、`learning_rate = 0.05`、`num_leaves = 31`、`[schedule]` `training = "30 0 * * *"`／`monitoring = "5 * * * *"`、`[health]` `min_precision = 0.5`、`min_recall = 0.5`、`min_f1 = 0.5`。每一筆訓練標籤之前都需要完整的 28 日門檻窗（672 小時），再加上 672 小時的訓練列，故最低累積為 1344 小時。

用電型態異常偵測任務設定 `tasks/load_pattern_anomaly.toml`：`task_type = "unsupervised_reconstruction"`、`subject = "nationwide"`、氣象代表點 `Taipei`（`temperature`、`relative_humidity`）、`min_training_hours = 672`、`stale_anchor_max_lag_hours = 3`、`validation_fraction = 0.2`、`window_hours = 24`、`threshold_quantile = 0.99`、`hidden_layer_sizes = [32, 8, 32]`、`alpha = 0.0001`、`learning_rate_init = 0.001`、`max_iter = 500`、`[schedule]` `training = "0 1 * * *"`／`monitoring = "0 * * * *"`、`[health]` `min_recall = 0.8`、`max_false_positive_rate = 0.05`。

## 2. 任務類型介面（`tasks/types/`）

任務類型為純計算 adapter，不接觸 repository；以 `tasks/types/__init__.py` 的明確 registry（`TASK_TYPES`、`get_task_type(name)`）依名稱對應。

- `name`、`params_model`：registry 名稱與 `[params]` 的 Pydantic model。
- `prediction_item`：`POST /tasks/{task_id}/predict` 單一預測 item 中任務類型自身欄位的 Pydantic model（[REST API §4](rest-api.md#4-通用任務推論)），欄位取自 `TaskModel.predict` 輸出，其餘欄位忽略。繼承 `WeatherEchoingItem` 者，服務層另補上任務設定 `weather.fields` 的每個天氣欄位（`float`）與 `weather_sources`，因此 item 的天氣欄位跟隨任務設定，任務類型不寫死天氣欄位。
- `requirements(params) -> InputRequirements(weather, lookback_hours, history_coverage)`：預測時使用預報（`FORECAST`）或觀測（`OBSERVED`）天氣，以及 runner 有界讀取歷史所需的小時數。`history_coverage`（必填、無預設值，型別為 `HistoryCoverage(window_hours, min_valid_hours) | None`；漏寫時建構 `InputRequirements` 即拋出 `TypeError`，不會靜默跳過檢查）要求錨點往前 `window_hours`（`(anchor - window_hours, anchor]`）內至少 `min_valid_hours` 個有實際負載的小時（`HistoryCoverage.complete(window_hours)` 表示每小時都要有）；不足時預測輸入關卡拋出 `InsufficientLoadHistoryError`，`/tasks/{task_id}/ready` 與 predict 皆回 503，任務類型不會收到歷史不足的 `PredictionData`（見下方預測輸入關卡）。明寫 `history_coverage=None` 表示刻意不檢查負載 lookback 完整性，任務類型須在旁以註解說明原因（例如容許缺口、自行跳過受影響的時間窗）。
- `train(params, TrainingData) -> Trained(model, metrics)`：負責特徵、標籤、fit 與評估。`TrainingData` 含 `load`（`datetime`、`subject`、`load_mw`）、`weather`（`datetime` 與 `weather.fields`，一律為觀測天氣）與 `validation_start`；target 時間 `>= validation_start` 者為驗證列，任務類型不得自行切分。
- `health_model`、`assess_health(thresholds, metrics) -> HealthAssessment(status, reason)`：健康判定規則屬於任務類型，門檻來自任務設定 `[health]`；`status` 為 `HealthStatus.HEALTHY` 或 `WARNING`，`reason` 指出決定判定的指標與門檻。缺少判定所需指標時必須回報 `WARNING`，不得視為健康。
- `load(directory, params, weather_fields) -> TaskModel`：讀取模型，並比對模型訓練時的輸入配方與任務設定目前宣告的 `[params]`、`weather.fields`；不一致即拋 `ModelRecipeMismatchError`（`ValueError` 的子類別），訊息逐一列出不同的項目並要求重新訓練。比對的項目只限決定輸入的部分：`recursive_regression` 為 `lags`、`rolling_windows`、`day_off`；`direct_classification` 為 `threshold`、`lags`、`rolling_windows`、`day_off`；`unsupervised_reconstruction` 為 `window_hours`；三者都比對氣象欄位。清單順序與模型超參數（`[params.model]`）不比對；`unsupervised_reconstruction` 的 `threshold_quantile` 也不比對，其門檻已在訓練時固定，新的分位數在下一次訓練生效。runner 依任務設定讀取歷史與天氣、模型卻用自己的配方建特徵，兩者不一致時不會有錯誤而是預測失真（例如任務設定拿掉 lag 168 後只讀 48 小時歷史，模型的 `lag_168` 全為缺值），因此改由載入時拒絕。`TaskModel.predict(PredictionData) -> DataFrame`、`TaskModel.save(directory)`。`PredictionData` 含 `anchor`、`load_history`、`weather`、`horizon_hours`，一律經預測輸入關卡交付：負載 lookback 完整性（依 `history_coverage`）與 `FORECAST` 任務目標時段的天氣欄位完整由關卡保證；負載起點新鮮則是 serving 的 runner 依請求時刻挑選起點時的規則，不在關卡內（滾動起點回測的起點由研究指定）。任務類型不得以常數補值；`load_history` 只含 `(anchor - lookback_hours, anchor]` 的列。`FORECAST` 任務的 `weather` 為錨點之後的預報（或降級來源）；`OBSERVED` 任務的 `weather` 為 `[anchor - lookback_hours, anchor]` 內的測站觀測，`horizon_hours` 表示評分最近幾個結束小時（[REST API §4](rest-api.md#4-通用任務推論)），`None` 表示評分 `load_history` 內所有完整時間窗。

已註冊任務類型：

- `recursive_regression`：LightGBM 單步模型遞迴展開（ADR-0003 僅適用此類型）；`lookback_hours = max(lags, rolling_windows)`；`requirements()` 宣告 `history_coverage = HistoryCoverage.complete(lookback_hours)`，負載起點往前 lookback 內缺任一小時的實際負載時由預測輸入關卡回報不可用（503），不以缺值推演 lag 或滾動窗，與滾動起點回測的起點有效性第 2 項相同（[研究空間 §2](lab.md#2-滾動起點回測labbacktestpy)）；負載缺口因此同樣使已發布預報在該 tick 留下缺口；預測輸出 `datetime`、`predicted_load_mw`；`prediction_item` 為 `RecursiveRegressionPrediction`（`datetime`、`predicted_load_mw`，附帶天氣）；動態視界預報任務的 item 因任務設定宣告 `temperature` 與 `relative_humidity`，與 `/predict` 的 `PredictionItem` 相同；評估為驗證列上的 one-step-ahead MAPE／RMSE／MAE；驗證列為空時不回報任何指標（不得以 `0.0` 佔位），健康判定因缺少 `mape` 而為 `WARNING`。健康判定：驗證期 `mape < max_mape` 為 `HEALTHY`，否則 `WARNING`。
- `direct_classification`：直接策略二元分類（高負載預警）。每個錨點（有實際負載的小時）與領先時數 `k = 1..168` 組成一列：特徵為錨點當下已知的 `anchor_load_mw`、`load_mw_lag_{L}`（錨點前 `L` 小時的負載）、`load_mw_rolling_mean_{W}`／`load_mw_rolling_std_{W}`（含錨點的前 `W` 小時）與 `threshold_mw`，目標小時的日曆特徵與天氣，以及 `lead_hours = k`；單一 `LGBMClassifier` 涵蓋整個視界，不串接任何預報輸出。高負載門檻 `threshold_mw` 為區間 `(anchor - window_days, anchor]` 內全台逐時實際負載的 `quantile` 分位數（線性內插），只使用錨點當下已知的資料；門檻窗內缺少任一小時的實際負載（28 日須完整 672 小時）時，該錨點不產生門檻與訓練列。`requirements()` 以同一規則宣告 `history_coverage = HistoryCoverage.complete(window_days × 24)`，預測時歷史不足由預測輸入關卡回報不可用（503）。標籤為目標小時實際負載 `>` 錨點門檻；觀測天氣缺漏的目標小時直接捨棄。訓練標籤只有單一類別時拒絕訓練。`lookback_hours = window_days × 24 + max(lags, rolling_windows)`。預測輸出與天氣列逐列對齊（每個預報小時一列、順序相同）：`datetime`、`is_high_load`（`probability >= 0.5`）、`probability`、`threshold_mw`；目標小時超出領先 1–168 小時時拋出錯誤。`prediction_item` 為 `DirectClassificationPrediction`（`datetime`、`is_high_load`、`probability`、`threshold_mw`，附帶天氣），item 另含任務 `weather.fields` 的天氣欄位與 `weather_sources`。評估為驗證列（目標小時 `>= validation_start`）上以 0.5 為界的 precision／recall／F1；驗證列為空時不回報任何指標，健康判定因缺少指標而為 `WARNING`。健康判定：三項指標皆 `>=` 各自的 `min_*` 為 `HEALTHY`；任一不足或缺少即 `WARNING`。
- `unsupervised_reconstruction`：淺層 MLP AutoEncoder（sklearn `MLPRegressor`，以輸入重建輸入）對滑動窗評分，偵測用電型態異常；訓練不需標籤。
  - **輸入**：`requirements()` 為 `OBSERVED` 天氣，`lookback_hours = window_hours + 168`，足以為最多 168 個結束小時各組一個完整時間窗；明寫 `history_coverage = None`，負載缺小時不使任務不可用，只跳過有缺口的時間窗。每個時間窗為結束小時（含）往前 `window_hours` 個連續小時：逐時全台實際負載、逐時 `weather.fields` 測站觀測、逐時週末旗標，加上結束小時的 hour-of-day 與 day-of-week sin/cos 編碼。觀測天氣最多向前補兩小時；負載缺小時或天氣缺口更長的時間窗不訓練也不評分。各特徵以訓練窗的平均與標準差標準化（訓練窗內為常數的特徵以 1 代替標準差；以最大值等於最小值判定，不以標準差是否為 0 判定，因為重複的浮點數其標準差只是接近 0 的捨入誤差）。
  - **分數與門檻**：`anomaly_score` 為時間窗負載部分（標準化後）的平均平方重建誤差；天氣與日曆只作為判斷條件，不計入分數。結束小時 `>= validation_start` 的時間窗為驗證窗，其餘為訓練窗。驗證窗依結束小時的日曆日由第一個驗證日起交錯分組：第 1、3、5… 個驗證日為校準日，第 2、4、6… 個為保留日；門檻為校準窗重建誤差的 `threshold_quantile` 分位數，`is_anomaly = anomaly_score > threshold`。以整日交錯而非前後對切，使驗證期短於一週時兩組仍分布於相同的平日與週末。沒有訓練窗或校準窗時無法設定門檻，拒絕訓練（`ValueError`）；驗證窗只落在單一日曆日（保留組為空）時只回報 `threshold` 與窗數，健康判定因缺少 `recall`／`false_positive_rate` 而為 `WARNING`。
  - **評估（寫入 MLflow）**：於乾淨保留窗注入三種合成異常並計算門檻下召回率：`recall_sudden_drop`（最後 6 小時負載降 20%）、`recall_pattern_swap`（窗內負載循環位移半個時間窗，24 小時窗即 12 小時）、`recall_level_shift`（整窗負載升 10%），`recall` 為三者平均；`false_positive_rate` 為乾淨保留窗被判為異常的比例；另記 `threshold`、`calibration_windows`（校準窗數）與 `validation_windows`（保留窗數）。門檻與誤報率取自不同日期的時間窗，誤報率不會因設計而固定接近 `1 - threshold_quantile`，保留日的重建誤差偏高時即可使 `max_false_positive_rate` 判定失敗。已知限制：時間窗以結束小時分組，保留日清晨結束的時間窗與前一個校準日深夜結束的時間窗共用最多 23 小時輸入，最早的驗證窗亦與訓練窗共用輸入，兩組並非完全獨立（取捨見 ADR-0009 Notes）。
  - **預測**：輸出 `datetime`（時間窗結束小時）、`anomaly_score`、`is_anomaly`、`threshold`；`prediction_item` 為 `UnsupervisedReconstructionPrediction`（同名四欄位，不附帶天氣）。
  - **健康判定**：`recall >= min_recall` 且 `false_positive_rate <= max_false_positive_rate` 為 `HEALTHY`，否則 `WARNING`；缺少任一指標時為 `WARNING`。

### 預測輸入關卡（`tasks/prediction_inputs.py`）

`admit_prediction_inputs(requirements, *, anchor, load, weather, weather_fields, horizon_hours, subject) -> PredictionData` 是唯一判定「這個負載起點的輸入夠不夠預測」的地方。它是純函式：不讀資料庫，也不知道請求時刻；呼叫端（serving 的 runner 與滾動起點回測，[研究空間 §2](lab.md#2-滾動起點回測labbacktestpy)）先挑選負載起點並取得資料，再把記憶體中的負載與天氣 frame 交給它。`load` 至少涵蓋 `(anchor - lookback_hours, anchor]`，可含 NaN 與更早的列；`FORECAST` 任務的 `weather` 為目標小時的天氣，`OBSERVED` 任務的為 lookback 內的觀測；`subject` 只用於拒絕訊息。`FORECAST` 任務傳入 `horizon_hours=None` 屬於呼叫端違反介面契約，拋一般的 `ValueError`，不是可回報 503 的輸入不足。

負載 lookback 完整性另以 `require_load_coverage(requirements, *, anchor, load, subject)` 單獨公開，讓 serving 能在讀取天氣之前拒絕負載不足的請求；`admit_prediction_inputs` 仍套用所有規則（含這一條）。

關卡內的規則：

- **負載 lookback 完整性**：依 `history_coverage` 判定，`FORECAST` 與 `OBSERVED` 任務都適用；`(anchor - window_hours, anchor]` 內有實際負載（非 NaN）的小時少於 `min_valid_hours` 時拋 `InsufficientLoadHistoryError`（`Only {n} {subject} load hours in the {window_hours}-hour window ending at anchor {anchor}; {min_valid_hours} required.`）。`history_coverage` 為 `None` 時不檢查。lookback 以外的缺值不影響判定。例外另以 `first_missing` 屬性帶出窗內第一個缺實際負載的小時，不放進訊息。
- **負載歷史裁切**：`load_history` 一律裁切到 `(anchor - lookback_hours, anchor]`。
- **目標時段天氣**：只有 `FORECAST` 任務檢查；目標小時 `anchor + 1h` 至 `anchor + horizon_hours` 每個小時的 `weather_fields` 皆須有值，否則拋 `WeatherUnavailableError`，訊息指出第一個缺值的目標小時與缺少的欄位。降級來源的天氣有值，視同涵蓋。

不在關卡內的規則：

- **負載起點過舊**：屬於 runner 依請求時刻挑選起點的那一步（`StaleLoadAnchorError`）；沒有任何負載時的 `MissingLoadHistoryError` 亦同。
- **天氣的取得**：預報或降級來源的解析、`OBSERVED` 任務的測站觀測讀取仍由 runner 負責；滾動起點回測則以 2 小時內向後對齊觀測氣象，兩者刻意不同。runner 的順序為：挑選並檢查負載起點、讀取 lookback 內負載、以 `require_load_coverage` 判定負載（不足時不讀天氣）、取得天氣、交給 `admit_prediction_inputs`。因此負載與天氣同時不足時回報負載不足。天氣無法取得（任一代表點無法涵蓋視界，或 lookback 內沒有任何觀測）時，取得步驟直接以其原因（指出代表點或觀測區間）拋 `WeatherUnavailableError`，不進入關卡。
- **`OBSERVED` 任務的天氣與時間窗完整性**：由任務類型組窗後判定；runner 的 readiness probe 與 `ObservedInputsIncompleteError` 照舊。

拒絕沿用 `TaskUnavailableError` 子類別；`TaskUnavailableError`、`InsufficientLoadHistoryError`、`WeatherUnavailableError` 定義於關卡模組，`tasks/runner.py` 重新匯出，既有匯入路徑與 API 的 503 對應不變。

## 3. Runner（`tasks/runner.py`）

Dagster 與 API 只經 runner 使用任務。runner 擁有 I/O 與共用元件（累積門檻、取資料、負載起點過舊、天氣解析與降級、加權天氣）；所有時間相關判斷皆傳入明確 `as_of`（台灣本地 naive 時間）。

| 函式 | 行為 |
| :--- | :--- |
| `check_training_readiness(task, runtime, *, as_of=None)` | 回傳累積摘要，其 `outcome`（`AccumulationOutcome`）為三種結果之一：`BLOCKED_BY_LEGACY_ROWS`（有 `source IS NULL` 的舊列，不論有效逐時觀測是否已達門檻）、`BELOW_MINIMUM_ACCUMULATION`（有效逐時觀測未達最低累積）、`MINIMUM_ACCUMULATION_REACHED`（唯一可訓練的結果）；`ready` 與 `reason` 皆由 `outcome` 導出。傳入 `as_of` 時只計該時間以前的有效逐時負載，全表任何時間的 legacy 列仍阻擋訓練；未傳入時供排程 skip 與 smoke check 檢查目前累積量 |
| `load_training_data(task, runtime, *, as_of)` | 未達門檻拋 `TaskNotReady`；讀取 `as_of` 以前的目標序列與同期觀測天氣，並以 `validation_fraction` 推導 `validation_start`。觀測天氣為加權天氣：各代表點在同一觀測整點皆有值才合成，任一點缺少的整點沒有加權值，交由任務類型既有的缺值規則處理 |
| `train_task(task, runtime, *, as_of) -> Trained` | `load_training_data` 後交由 `fit_task` |
| `fit_task(task, data) -> Trained` | 以已讀取且通過門檻的 `TrainingData` 交由任務類型訓練 |
| `training_table(data)`／`training_data_from_table(task, table)` | 以目標序列與觀測天氣的時間軸聯集將 `TrainingData` 攤平序列化以便跨 run 保存（包含無負載但有觀測天氣的小時），並無損還原：`load` 只保留有 `load_mw` 的列、`weather` 只保留有任一氣象欄位值的列（完全沒有觀測天氣的小時仍為缺口而非 NaN 列），`validation_start` 由還原後的目標小時以相同切分規則重算 |
| `monitor_task(task, runtime, metrics, *, as_of) -> MonitoringReport` | 未達門檻拋 `TaskNotReady`；以有界查詢讀取有效逐時觀測數與 `as_of` 以前最新目標列，交由任務類型 `assess_health` 依 `[health]` 判定；結果含 `health`、`metrics`、`target_hours`、`latest_target_time`、`latest_target_value` |
| `check_task_ready(task, model, runtime, *, as_of) -> Ready \| InputsUnavailable` | 呼叫端須提供已載入的模型；只回兩態之一。負載起點、任務類型宣告的 `history_coverage` 與完整 168 小時天氣皆可用時回 `Ready`，帶預報運行狀態 `mode`（`ForecastMode`）；`OBSERVED` 任務只需 lookback 內有測站觀測，`mode` 固定 `normal`。上述任一項不可用（`TaskUnavailableError`）時回 `InputsUnavailable`，帶拒絕訊息 `reason`、不帶 `mode`。資料庫錯誤（`SQLAlchemyError`）與其他例外原樣拋出，由 `ServedTasks` 分類（[REST API §2](rest-api.md#2-就緒狀態檢查)） |
| `predict_task(task, model, runtime, *, as_of, horizon_hours) -> PredictionOutcome` | 拋出 `MissingLoadHistoryError`、`StaleLoadAnchorError`、`InsufficientLoadHistoryError`、`WeatherUnavailableError`、`ObservedInputsIncompleteError`（皆為 `TaskUnavailableError`，API 對應 HTTP 503）；資料庫錯誤（`SQLAlchemyError`）原樣拋出，不得轉為空資料而偽裝成資料缺口（API 同樣對應 503）；結果含負載起點 `load_anchor`、`mode`、預測、逐時天氣與其來源，後三者逐列對應 |

`TaskRuntime` 只持有 runner 讀取的兩個 store，即全台逐時實際負載（`hourly_actual_load`）與 CWA 天氣（`cwa_weather`），不持有 `TimeSeriesRepository`。Dagster 任務管線與已發布預報 asset、API 的 `ServedTasks`、smoke check 與 lab snapshot 都以 `TaskRuntime.from_composition_root(root)` 建構它：這個唯一的 factory 從 composition root（`src/shiro_mlops/data/repository.py` 的 `TimeSeriesRepository`）取出這兩個 store，不保留 root 的參照；`ServedTasks` 只收 `TaskRuntime`。

runner 經 `TaskRuntime.hourly_actual_load` 取得全台逐時實際負載 store（`src/shiro_mlops/data/hourly_actual_load_store.py` 的 `HourlyActualLoadStore`），目標序列、負載起點與累積摘要都只由它讀取，只含推算來源的列。store 的序列只接受台灣本地半開窗 `[start, end)`；訓練序列（至 `as_of`，含）與 serving 歷史（至負載起點，含）都包含終點所在的小時，由 runner 在單一處把終點換成該小時的下一小時。

serving 以 store 的 `latest_observation(as_of)` 取得負載起點並檢查是否過舊，再只讀 `[anchor - lookback_hours, anchor]` 的負載歷史、取得天氣，交由[預測輸入關卡](#預測輸入關卡tasksprediction_inputspy)判定並裁切負載歷史後才交給任務類型。

天氣經 `TaskRuntime.cwa_weather` 取得 CWA 天氣 store（`src/shiro_mlops/data/cwa_weather_store.py` 的 `CWAWeatherStore`）：訓練與 `OBSERVED` 任務的觀測天氣由它讀取各代表點的測站觀測，預報天氣的解析則把它交給 `resolve_weather`。兩者都直接收任務設定載入時解析出的氣象代表點（`CWALocation`），測站與預報區皆取自它，觀測結果的 `location` 標其 alias；store 不讀全域 settings 的 CWA 擷取目錄。

`OBSERVED` 任務的 serving 路徑：負載起點過舊檢查照常適用；天氣改讀同一區間 `[anchor - lookback_hours, anchor]` 的測站觀測（加權規則同 `load_training_data`），不讀預報也不降級，`mode` 固定 `normal`。區間內沒有任何觀測時拋 `WeatherUnavailableError`；任務類型未能評分任何請求的結束小時（負載或天氣缺口）時拋 `ObservedInputsIncompleteError`。`PredictionOutcome.weather` 與 `weather_sources` 對齊至每個被評分的結束小時，取該小時以前最新一筆觀測，來源為 `station_observation` 並附 `observed_at`。

天氣數值的來源：預報天氣路徑（`resolve_weather`）、觀測天氣路徑與加權天氣（`tasks/weighted_weather.py`）逐值傳遞 `data/weather_resolution.py` 的 `WeatherValueSource`，不自行組來源字串。來源種類 `WeatherSourceKind` 是封閉集合：`three_day`、`weekly`（預報，帶產生該值的預報版本 `dataset_id`、`issued_at`、`source_updated_at`）、`previous_day_observation`、`climatology`（替代來源，不帶欄位）、`station_observation`（測站觀測，帶 `observed_at`）；只有兩種替代來源的 `is_substitute` 為真。欄位與種類不符的來源在建構時即拋 `ValueError`，`WeatherValueSource.substitute` 也拒絕非替代來源的種類。`predict_task` 把來源以 `as_dict()` 序列化為 `PredictionOutcome.weather_sources`，即 API `weather_sources` 的 JSON 形狀（[REST API §3](rest-api.md#3-隨需動態視界負載預報)）。

預報天氣的無覆蓋只以拒絕表達：`resolve_weather` 遇到某代表點某小時的某欄位既沒有七小時內的預報版本、也沒有替代來源時，拋 `WeatherCoverageError`，訊息為 `"{代表點}: No weather coverage for {時刻} {欄位}"`；解析結果 `WeatherResolution` 只在每小時、每欄位皆有值時存在。`horizon_hours < 1` 屬呼叫端違反介面契約，拋一般的 `ValueError`。runner 依任務設定的代表點順序逐點解析，第一個無覆蓋的代表點即中止；`_resolve_future_weather` 是唯一把 `WeatherCoverageError` 轉成 `WeatherUnavailableError`（同一訊息）的地方，`data/` 不依賴 `tasks/`。加權天氣只接收完整的解析結果，不處理無覆蓋。

預報運行狀態（[GLOSSARY](../../GLOSSARY.md) §3）只有一個出處：`data/weather_resolution.py` 的 `ForecastMode`（StrEnum，`normal`、`degraded` 兩值；無法產出不是運行狀態，只以上述拒絕表達）。`forecast_mode(sources)` 接受以序列或 mapping 巢狀的來源，在任一數值的來源 `is_substitute` 時回傳 `degraded`，否則 `normal`；`WeatherResolution.mode` 與加權天氣 `WeightedWeather.mode` 都是由各自來源推導的 property，不另存欄位或旗標。多代表點時加權天氣保留每個代表點的來源，因此任一點降級即整次降級（ADR-0012）；觀測天氣路徑的來源全為 `station_observation`，不是替代值，所以 `mode` 為 `normal`。`PredictionOutcome.mode` 型別為 `ForecastMode`，在來源序列化為 `weather_sources` 前由加權天氣推導；`Ready.mode` 同為 `ForecastMode`，`InputsUnavailable` 不帶 `mode`。

## 4. 模型保存（`tasks/model_store.py`）

- **模型版本識別**：`model_directory_sha256(directory) -> str` 為模型目錄檔案內容的 SHA-256（完整 64 字元小寫十六進位），不依賴 MLflow。目錄內所有檔案（含子目錄）依相對 POSIX 路徑排序，每個檔案依序餵入 UTF-8 相對路徑、一個 NUL 位元組、檔案大小（8 位元組 big-endian）與檔案內容；因此雜湊只取決於相對路徑與內容，不受檔案時間戳、列舉順序或目錄所在位置影響，改動任一檔案內容、新增或更名檔案則雜湊改變。訓練固定 seed，相同模型得到相同識別。
- `save_model(root, task_id, model) -> SavedModel`：回傳 `SavedModel(directory, sha256)`，`sha256` 取自暫存目錄（即安裝的同一組檔案）。模型先寫入暫存目錄；Linux 上以 `renameat2(RENAME_EXCHANGE)` 原子交換新舊非空目錄，首次寫入則以單次 rename 安裝；核心或檔案系統不支援交換（`ENOSYS`、`EINVAL`）時，於同一把排他鎖內以 rename 依序移開舊目錄、安裝新目錄，讀取端因等待鎖而不會看到空窗；僅程序於兩次 rename 之間中止時，任務於下次訓練成功前沒有模型，遺留的舊目錄 `.<task_id>.previous` 於下次保存（持排他鎖、安裝前）清除。每任務檔案鎖 `root/.<task_id>.lock` 保護交換與讀取：只有保存端（排他鎖）會建立鎖檔，且於首次安裝模型目錄前建立；讀取端（共享鎖）以唯讀模式開啟既有鎖檔、不建立鎖檔，因此 `root` 可唯讀掛載（本機 compose 的 API 即唯讀掛載）。交換失敗時舊模型仍在正式路徑。`root` 為 `DATA_DIR/models`。
- `load_model_with_sha256(root, task) -> LoadedModel | None`：在同一把共享鎖下讀取 `root/<task_id>` 並計算該目錄雜湊，回傳 `LoadedModel(model, sha256)`；交換須等鎖釋放，故載入的模型與雜湊必屬同一目錄版本，不會是半新半舊的組合。目錄不存在時回傳 `None`（任務尚未訓練；鎖檔是否存在皆同，舊版讀取端曾為未訓練任務建立鎖檔）；目錄存在而鎖檔不存在時再找一次鎖檔（涵蓋首次訓練恰於此時建立鎖檔並安裝目錄），仍不存在則拋 `MissingModelLockError`（該目錄非由 `save_model` 安裝，例如手動複製，重新訓練即取代）；既有 `model.joblib` 不載入。
- `load_model(root, task) -> TaskModel | None`：同上，只回傳模型；替換期間只會載入完整的前一版或新模型。
- `has_installed_model(root, task_id) -> bool`：以與 `load_model_with_sha256` 相同的規則（同一把共享鎖、鎖檔與目錄皆須存在）判斷任務有沒有可載入的模型，但不載入模型、不計算雜湊；非由 `save_model` 安裝的目錄（載入時會拋 `MissingModelLockError`）視為沒有模型。冷啟動階段（[Dagster 排程 §1](dagster-schedules.md)）以此判斷模型目錄。
- 模型檔只使用原生非執行格式：`recursive_regression` 為 `model.txt`（LightGBM Booster 文字格式）與 `metadata.json`（格式版本、任務類型、lag、rolling window、特徵名稱、氣象欄位）；`direct_classification` 同為 `model.txt`（二元分類 Booster 文字格式）與 `metadata.json`（格式版本、任務類型、完整 `[params]`、`max_lead_hours`、特徵名稱、氣象欄位）；`unsupervised_reconstruction` 為 `model.npz`（`coef_{i}`、`intercept_{i}` 各層權重與偏差，`scaler_mean`、`scaler_scale` 標準化參數；以 `allow_pickle=False` 讀取）與 `metadata.json`（格式版本、任務類型、激活函數、層數、`window_hours`、氣象欄位、特徵名稱、`threshold`），推論以 numpy 前向計算，不重建 sklearn 物件。
- `src/` 不得 import `pickle` 或 `joblib`，由測試強制。
