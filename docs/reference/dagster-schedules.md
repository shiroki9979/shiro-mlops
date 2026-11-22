# Dagster 資產排程與觸發規格

- 建立日期：2026-11-20
- 最後更新：2026-11-22
- 專案版本：`0.4.0`

> 由 `docs/SPEC.md` 第 3 節拆出。

---

1. **任務資產工廠（`pipelines/task_pipelines.py`）**：
   - **生成規則**：Dagster code location 載入時，依 `deployed_tasks()` 為每份任務設定（[ML 任務設定 §1](ml-tasks.md#1-任務設定-schemataskstask_idtoml)）產生下列定義；新增一份任務設定即新增一組，不需改動程式。名稱以 `__` 分隔任務 id 與後綴，資產 group 為 `task_id`。

     | 種類 | 名稱 | 內容 |
     | :--- | :--- | :--- |
     | 資產 | `{task_id}__features` | 經 runner `load_training_data` 讀取並套用最低累積，輸出 `training_table`（以目標序列與觀測天氣的時間軸聯集為主鍵序列化：`datetime`、`subject`、`load_mw` 與 `weather.fields`，保留負載缺漏小時的觀測天氣；`rows` metadata 為訓練表總列數）；lineage 依賴 `raw_taipower_load` 與 `raw_cwa_station_observation`，但不執行它們 |
     | 資產 | `{task_id}__model` | 以 `training_data_from_table` 還原上游訓練表後經 `fit_task` 訓練，不再重讀資料庫；模型存入 `DATA_DIR/models/{task_id}/`，並寫入 MLflow（見下）。輸出 `task_id`、`metrics`、`run_id`、`model_version`、`model_path`、`training_rows`；materialization metadata 除各 metric 外，另記 `model_sha256`（剛保存的模型目錄雜湊，定義見 [ML 任務設定 §4](ml-tasks.md#4-模型保存tasksmodel_storepy)）與 `mlflow_model_version`（MLflow model version；MLflow 不可用、`run_id` 為 `local_run` 時為空值，`model_sha256` 照常記錄） |
     | 資產 | `{task_id}__monitoring` | 經 runner `monitor_task` 以有界查詢讀取有效逐時觀測數與 `as_of` 以前最新一列（僅 `source = 'regional_snapshot_sum'`），再由任務類型 `assess_health` 以任務設定 `[health]` 門檻判定；輸出 `task_id`、`status`（`HEALTHY`／`WARNING`）、`health_reason`、`metrics`、`training_rows`、`target_hours`（有效逐時目標觀測數）、`latest_target_time`、`latest_target_value`（目前任務的目標皆為逐時實際負載，單位 MW） |
     | job | `{task_id}__training_job` | selection 為 `{task_id}__features` 及其所有下游（model、monitoring，以及只掛在該任務的資產，例如 Feast 匯出） |
     | job | `{task_id}__monitoring_job` | selection 僅含 `{task_id}__monitoring`；model 輸出取自最近一次訓練的 I/O Manager 產物，不重跑讀取完整歷史的 features |
     | 排程 | `{task_id}__training_schedule` | cron 取自 `[schedule].training`，時區 `Asia/Taipei`；最低累積未達時以 `SkipReason` 揭露差距 |
     | 排程 | `{task_id}__monitoring_schedule` | cron 取自 `[schedule].monitoring`，時區 `Asia/Taipei`；除最低累積外，另需 `{task_id}__model` 已有 materialization |

   - **邊界**：擷取資產（台電快照、逐時負載推算、CWA 觀測與預報）以資料來源為中心、跨任務共用，不隨任務生成；任務的兩個 job 皆不得選取任何擷取資產，也不得選取 `issued_forecast`（見第 6 項）、`forecast_track_record`（見第 7 項）或 `forecast_view_export`（見第 8 項）。資產只經 runner（[ML 任務設定 §3](ml-tasks.md#3-runnertasksrunnerpy)）取門檻、資料、訓練與監控結果。
   - **排程 run_key**：排程 tick 轉為台灣本地時間 ISO 字串作為 `run_key`，同一 tick 重複評估不重跑；無 tick 的手動評估不帶 `run_key`。
   - **MLflow**：每個任務擁有獨立 experiment 與 registered model，名稱皆等於 `task_id`。每次訓練以 `{task_id}_training` 為 run 名稱記錄 metrics、攤平的 `[params]`（巢狀鍵以 `.` 連接，另含 `task_id`、`task_type`）與模型目錄（artifact path `model`），並以該 artifact URI 建立新的 model version（模型為原生檔案而非 MLflow logged model，ADR-0010）。MLflow 不可用時記錄警告、`run_id` 標為 `local_run`，已保存的模型仍有效。
   - **動態視界預報任務**：`dynamic_horizon_forecast__training_schedule` 為 `0 0 * * *`（`Asia/Taipei`，與舊版 `0 16 * * *` UTC 同一時刻），`dynamic_horizon_forecast__monitoring_schedule` 為 `0 * * * *`；健康門檻 `max_mape = 10.0`。
   - **高負載預警任務**：`high_load_alert__training_schedule` 為 `30 0 * * *`（錯開動態視界預報 00:00 與用電型態異常偵測 01:00 的訓練），`high_load_alert__monitoring_schedule` 為 `5 * * * *`；健康門檻 `min_precision`／`min_recall`／`min_f1` 皆為 `0.5`。
   - **用電型態異常偵測任務**：`load_pattern_anomaly__training_schedule` 為 `0 1 * * *`（錯開前兩項任務的訓練）、`load_pattern_anomaly__monitoring_schedule` 為 `0 * * * *`（皆 `Asia/Taipei`）；MLflow metrics 含合成異常召回率與乾淨資料誤報率（[ML 任務設定 §2](ml-tasks.md#2-任務類型介面taskstypes)）；健康門檻 `min_recall = 0.8`、`max_false_positive_rate = 0.05`。
   - **Feast 發布**：`dynamic_horizon_forecast_feast_export`（輸出 `taipower_features` 與 `weather_features`）只以 `dynamic_horizon_forecast__features` 為輸入，因此只在該任務的訓練 job 中執行；天氣匯出只含訓練表中有觀測值的小時。兩者透過 `feast_io_manager`（`FeastParquetIOManager`）寫入本機 `DATA_DIR`。
   - **更名遷移**：舊版的 `daily_training_job`／`hourly_drift_job`、其排程，以及資產 `taipower_load_feature_source`、`cwa_observation_feature_source`、`engineered_features`、`trained_forecaster_model`、`drift_monitoring_report` 已移除。Dagster 不會把舊資產鍵的 materialization 歷史轉移到新鍵：監控排程只認 `{task_id}__model`，部署後須先成功執行一次 `{task_id}__training_job`。新排程預設為停用，須在 Dagster UI 開啟。舊的單一 MLflow experiment（`MLFLOW_EXPERIMENT_NAME`）不再使用，既有 run 保留但不再增加。
   - **最低累積（訓練與監控共用）**：
     - `raw_taipower_load` 有效逐時觀測少於任務設定 `[policies].min_training_hours`（動態視界預報任務為 `672`，即 28 日；高負載預警任務為 `1344`，即 56 日）時，訓練與監控必須明確失敗或略過並揭露原因，不得以不足資料產出模型或報告。有效逐時觀測指 `source = 'regional_snapshot_sum'` 的列；存在 `source IS NULL` 的舊列時視為未就緒。
     - 排程 tick 以 `SkipReason` 揭露差距；runner 拋出領域錯誤 `TaskNotReady`，手動執行時由 `{task_id}__features` 或 `{task_id}__monitoring` 轉為 Dagster `Failure` 並附 `valid_hours`／`required_hours`／`legacy_rows` metadata。
2. **`taipower_supply_demand_snapshot_job`**：
   - **排程**：`*/10 * * * *`；抓取失敗時在同一 run 內有限次重試，不另以更高頻率輪詢。全台與機組快照最多重試兩次、每次間隔十秒；區域快照為全台逐時實際負載的唯一來源且無法回補，最多重試三次，以十秒起算指數退避（依序等待 10、30、70 秒，約 110 秒內結束）。
   - **管線鏈路**：`raw_taipower_supply_demand_snapshot`、`raw_taipower_regional_supply_demand_snapshot` 與 `raw_taipower_unit_generation_snapshot` 資產擷取台電當前全台供需、各區域供需與各機組即時淨發電量並 upsert 至 TimescaleDB；三者皆不得進入任何任務的 `{task_id}__training_job` 或 `{task_id}__monitoring_job`；區域快照僅能經由 `hourly_actual_load_job` 推算後間接供訓練使用。
   - **冪等性**：排程觸發以 tick 時間作為 `observed_at`；手動 materialize 則以實際抓取起始時間向下取整至 10 分鐘。全台快照以 `observed_at` 為鍵；區域快照以 `(observed_at, region)` 為鍵；機組快照以 `(observed_at, unit_type, unit_name)` 為鍵。相同 slot 重跑時皆更新同一快照。
   - **資料完整度與失敗政策**：
     - 全台：`curr_load` 與 `curr_util_rate` 為必填欄位；缺少、無法解析，或 HTTP／重試最終失敗時，asset 必須失敗且不得寫入快照。預估尖峰、昨日尖峰與實際最高供電能力資料組可缺少，對應 typed 欄位保存為 `NULL`，完整來源回應仍保存於 `raw_payload`。
     - 區域：來源列缺少核心 `時間`、`區域` 或 `用電(萬瓩)`、或無法解析時，略過該列且不寫入該區域快照；`發電(萬瓩)` 可缺少並保存為 `NULL`。HTTP／重試最終失敗，或成功回應中無任何有效區域列時，asset 必須失敗且不得寫入。
     - 機組：來源列缺少 `機組類型` 或 `機組名稱` 時略過該列；`淨發電量(MW)` 為 `0.0` 時仍寫入；`N/A`／`-` 的發電量、裝置容量或容量比保存為 `NULL`；備註空白保存為 `NULL`。HTTP／重試最終失敗，或成功回應中無任何有效機組列時，asset 必須失敗且不得寫入。
3. **CWA 逐時測站觀測擷取工作**：
   - **排程**：`10 * * * *`（`Asia/Taipei`）；失敗時在同一 run 內最多重試三次，以三十秒起算指數退避（Dagster 依序等待 30／90／210 秒，約 5.5 分鐘內結束）；重試用盡時 run 必須失敗且不得改動既有資料。
   - **故障邊界**：使用獨立 job 與 schedule，不與台電即時快照、任務訓練或監控工作共用成敗狀態。
4. **CWA 鄉鎮預報版本擷取工作**：
   - **排程**：`40 * * * *`（`Asia/Taipei`）；每小時檢查 `F-D0047-089` 與 `F-D0047-091`，以 `(dataset_id, IssueTime, Update)` 去重；失敗時在同一 run 內最多重試三次，以三十秒起算指數退避；重試用盡時 run 必須失敗且不得改動既有預報版本。
   - **故障邊界**：使用獨立 job 與 schedule，不因觀測擷取或其他管線失敗而跳過當次預報版本。
5. **`hourly_actual_load_job`**：
   - **排程**：`5 * * * *`（`Asia/Taipei`）。
   - **管線鏈路**：讀取 `raw_taipower_regional_supply_demand_snapshot`，依 [資料契約 §1](data-contracts.md#1-台電用電負載實體-taipower-load-schema) 推算已結束小時，以 `(time, subject)` upsert 至 `raw_taipower_load`，`subject` 為 `nationwide`；不呼叫任何台電外部 API。
   - **推算窗口**：最近 `HOURLY_LOAD_RECOMPUTE_HOURS`（預設 `3`）個已結束小時，並向前延伸至 tick 時已存在的最後一個推算小時（`source = regional_snapshot_sum`）之後，使擷取中斷前已入庫、尚未推算的小時在排程恢復後補上；最多回溯 `HOURLY_LOAD_CATCHUP_MAX_HOURS`（預設 `168`）個小時，尚無推算小時時即回溯此上限。超出上限而未涵蓋的區間以 warning 記錄於 run log，改由 `scripts/rederive_hourly_actual_load.py` 補算。
   - **冪等性**：排程以 tick 時間決定重算窗口，手動 materialize 以實際執行時間決定；重算同一小時得到相同結果；後到的有效樣本可使先前缺值的小時補上或更新平均值。
6. **`issued_forecast_job`（已發布預報，[ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md)）**：
   - **定義**：固定資產 `issued_forecast`、job `issued_forecast_job`、排程 `issued_forecast_schedule`，位於 `pipelines/issued_forecast.py`，不進任務資產工廠；只發布動態視界預報。排程預設停用，於首次訓練成功後開啟。
   - **排程**：`15 * * * *`（`Asia/Taipei`），排在逐時負載推算（:05）與觀測擷取（:10）之後。tick 轉為台灣本地時間 ISO 字串，同時作為 `run_key` 與資產設定 `issued_at`。
   - **發布時刻**：發布時刻即排程 tick 時刻，也是預報的 `as_of`，不取整點（決策見 [#136](https://github.com/shiroki9979/shiro-mlops/issues/136)）。
   - **管線鏈路**：經 runner `predict_task`（[ML 任務設定 §3](ml-tasks.md#3-runnertasksrunnerpy)）以 H = 168 預報，降級與負載起點過舊規則照舊；以 `load_model_with_sha256` 在同一把鎖下取得載入的模型與其雜湊，寫入 [資料契約 §3](data-contracts.md#3-地端時序資料庫模型-timescaledb-hypertables) 的 `issued_forecast` 與 `issued_forecast_step`。不讀模型健康檢查：`{task_id}__monitoring` 為 `WARNING` 時照常發布。
   - **lineage**：只依賴 `raw_taipower_load`、`raw_cwa_station_observation` 與 `raw_cwa_township_forecast`，但不執行它們；不依賴 `{task_id}__model`，因此任務 job 不會帶出發布（見第 1 項邊界）。`issued_forecast_job` 不選取任何擷取資產。
   - **只有定時發布才算**：資產只接受由 `issued_forecast_schedule` tick 產生的 run（設定帶 `issued_at` 且 run 帶 `dagster/schedule_name` 標籤）；手動 materialize、在 launchpad 自填 `issued_at` 的 run，以及重新執行的 run（帶 `dagster/parent_run_id` 或 `dagster/root_run_id` 標籤，即使沿用原 tick 的設定與標籤）皆以 `Failure` 結束、不寫入，因此不補發。無 tick 的手動排程評估以 `SkipReason` 略過。隨需 `/predict` 不寫入。
   - **無法產出**：尚無 `dynamic_horizon_forecast__model` materialization 時，排程以 `SkipReason` 略過。負載起點過舊、天氣不可用、歷史不足（`TaskUnavailableError`）時，資產以 `Failure` 結束、description 為 runner 的原因並附 `issued_at` metadata，不寫入；模型目錄不存在時同樣以 `Failure` 結束。
   - **不設重試政策**：`issued_forecast` 資產與 `issued_forecast_job` 皆無重試政策；重新執行的 run 不寫入（見上）。理由見 [ADR-0013 §2.1](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md#21-已發布預報) 的不補發與 [#136](https://github.com/shiroki9979/shiro-mlops/issues/136)。
   - **冪等性**：同一發布時刻已有紀錄（例如 commit 後崩潰被重跑）時不預報、不寫入、不覆寫，資產成功並以 metadata `already_issued = true` 標示；新寫入時 metadata 另記 `load_anchor`、`status`、`model_sha256` 與步數。
7. **`forecast_track_record`（預報實績，[ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md)）**：
   - **定義**：固定資產 `forecast_track_record`，位於 `pipelines/forecast_track_record.py`，不進任務資產工廠。lineage 依賴 `issued_forecast` 與 `raw_taipower_load`，但不執行它們；任務的兩個 job 與 `issued_forecast_job` 皆不選取它。
   - **排程**：job `forecast_track_record_job` 與排程 `forecast_track_record_schedule` 同位於 `pipelines/forecast_track_record.py`。排程為 `25 * * * *`（`Asia/Taipei`），排在發布（:15）之後；tick 轉為台灣本地時間 ISO 字串，同時作為 `run_key` 與資產設定 `scheduled_at`。無 tick 的手動排程評估不帶 `run_key` 與設定，run 以執行當下為準。job 只選取 `forecast_track_record`，不選取任何擷取資產，也不選取 `issued_forecast`，因此發布失敗或略過時照常彙整。排程預設停用，冷啟動時與擷取排程一起開啟，不需等待首次訓練。
   - **重試政策**：`forecast_track_record_job` 失敗時在同一 run 內最多重試兩次，每次間隔六十秒，用盡後仍遠早於下一個 tick。彙整只讀資料庫、從頭重算且不保存歷次結果，可吸收短暫的資料庫中斷。排程觸發的 run 重試時沿用同一 `scheduled_at`，得到同一統計窗；手動執行（未設定 `scheduled_at`）的重試以重試當下取整點，跨過整點時統計窗隨之後移一小時。`issued_forecast` 刻意不重試（第 6 項），是因為重試會沿用原 tick 為 `as_of` 卻讀到其後入庫的負載；彙整沒有 `as_of`，不受此限。
   - **統計截至時刻 E**：執行時點取整點。資產設定 `scheduled_at`（台灣本地時間 ISO 字串）帶入排程 tick 時，執行時點為該 tick；未設定時（手動 materialize）為執行當下。
   - **統計窗**：目標小時 ∈ [E − 720h, E)，以目標小時判斷，與發布時刻無關；窗開始前發布、目標小時落在窗內的步數也計入。
   - **配對與計入**：提前時數 = ⌈(目標小時 − 發布時刻) / 1h⌉，不大於 0 的步數不計入，例如 10:15 發布時 10:00 不計入、11:00 為提前 1、隔天 10:00 為提前 24。只配對有有效逐時觀測的目標小時，即 `raw_taipower_load` 中 `subject = 'nationwide'`、`source = 'regional_snapshot_sum'` 的列。降級預報照常計入。
   - **有界查詢**：repository `fetch_track_record_pairs` 以一條 SQL join，依目標小時把已發布預報步數對上窗內的有效逐時觀測，只回傳配對成功的列（發布時刻、目標小時、預測值、實際值）。只讀目標小時在窗內、發布時刻晚於窗起點前 168 小時的步數（步數最遠落在負載起點後 168 小時，而負載起點早於發布時刻），不讀整段歷史；提前時數與 MAPE／MAE 等彙總在 Python 計算。
   - **累積天數**：窗內有配對的目標小時，取台灣日期去重後的天數，最多 31。
   - **重算**：每次都從頭重算、不保存歷次結果，因此允許手動執行、重試與重新執行，事後推算補上的小時在下次彙整自然計入。尚無已發布預報時照常成功，累積天數為 0。
   - **輸出與 metadata**：輸出格式見 [資料契約 §5.1](data-contracts.md#51-預報實績-forecast_track_record)。materialization metadata 記 `cutoff`（統計截至時刻）、`accumulated_days`、`window_pairs`（窗內總配對數）與 `lead_24_pairs`（窗內提前 24 的配對數，未滿 7 天也記），只在 Dagster UI 可見，不匯出。
8. **`forecast_view_export`（預報檢視匯出，[ADR-0015](../adr/0015-publish-forecast-view-as-static-precomputed-output.md)）**：
   - **定義**：固定資產 `forecast_view_export`、job `forecast_view_export_job` 與排程 `forecast_view_export_schedule`，位於 `pipelines/forecast_view_export.py`，不進任務資產工廠。以 input 讀取最近一次 `forecast_track_record` 的 artifact，lineage 另依賴 `issued_forecast`，兩者都不執行；最新已發布預報由 repository `fetch_latest_issued_forecast` 讀取。任務的兩個 job、`issued_forecast_job` 與 `forecast_track_record_job` 皆不選取它。
   - **排程**：`35 * * * *`（`Asia/Taipei`），排在發布（:15）與預報實績彙整（:25，含重試約於 :28 前結束）之後。tick 轉為台灣本地時間 ISO 字串作為 `run_key`，不帶資產設定：匯出的是執行當下最新的已發布預報與預報實績，與 tick 時刻無關。job 只選取 `forecast_view_export`，因此彙整失敗或略過時照常匯出最新已發布預報，預報實績則沿用上一次成功彙整的統計截至時刻。排程預設停用，冷啟動時與 `forecast_track_record_schedule` 一起開啟，不需等待首次訓練。
   - **先寫地端，再上傳**：兩份 JSON（格式見 [資料契約 §6](data-contracts.md#6-預報檢視公開-jsonpublished)）先寫入 `DATA_DIR/published/`，每個檔案先寫暫存檔再以 rename 替換，Nginx 不會讀到寫一半的檔案；全部寫完後，有設定 `FORECAST_VIEW_S3_BUCKET` 時再以 `PutObject` 上傳同樣的位元組到 bucket 的 `published/` prefix（`Content-Type: application/json`，不設 `Cache-Control`）。未設定 bucket 時不建立 S3 client。上傳設定見 [預報檢視託管 §1](forecast-view-hosting.md#1-s3-配置與寫入權限)。
   - **失敗與重試**：上傳失敗時 run 失敗、在地端 Dagster 執行紀錄可見，地端目錄已是本次內容。`forecast_view_export_job` 失敗時在同一 run 內最多重試兩次、每次間隔六十秒；匯出覆寫固定檔名，重試、手動執行與重新執行皆安全。從未 materialize 過 `forecast_track_record` 時（全新環境），input 為空，匯出照常寫出並上傳最新已發布預報，預報實績寫出累積 0 天、統計截至時刻為匯出執行當下整點的空狀態（[資料契約 §6.2](data-contracts.md#62-預報實績-forecast_track_recordjson)）。曾 materialize 過但 artifact 遺失時，input 讀取失敗，run 以錯誤結束，不當成全新環境。
   - **尚無已發布預報**：照常成功，最新已發布預報輸出空狀態（[資料契約 §6.1](data-contracts.md#61-最新已發布預報-latest_issued_forecastjson)）。
   - **metadata**：`issued_at`（無已發布預報時為空字串）、`published_steps`、`cutoff`、`accumulated_days`、`local_dir` 與 `uploaded_to_s3`。
9. **CWA 消費邊界**：
   - 外部 CWA API 僅由兩個 ingestion jobs 呼叫；模型訓練與線上預測一律讀取 canonical TimescaleDB tables，不得在缺資料時繞過 ingestion 邊界直接呼叫 CWA。
   - 三個任務目前只使用氣象代表點 `Taipei`（測站與預報區見 [資料契約 §2](data-contracts.md#2-中央氣象署資料實體-cwa-weather-schemas) 目錄）。任務設定可依 [ML 任務設定 §1](ml-tasks.md#1-任務設定-schemataskstask_idtoml) 列出多個加權代表點（ADR-0012），是否採用由 TICKET-303 的滾動起點回測判定。
10. **本機冷啟動**：
    - 空資料庫啟動後，台電即時快照排程須先累積區域快照，且 `hourly_actual_load_job` 產出的有效逐時觀測達訓練最低累積；之後由操作人員依序 materialize CWA 觀測資產、CWA 預報資產與訓練工作；完成前 `/ready` 回傳 HTTP 503。
    - 不新增一次性 bootstrap sensor，也不等待每日訓練排程自然觸發。
    - 操作人員以 `python -m shiro_mlops.pipelines.smoke_check`（`make smoke-check`）在 Dagster 容器內檢查排程註冊與啟用狀態（任務排程的期望 cron 由任務設定推導）、各任務訓練與監控 job 的 selection 邊界，以及每個任務的累積進度（`{task_id} load accumulation`）、新鮮度（`{task_id} load freshness`）與兩個任務排程下一次 tick 的結果，並檢查 `issued_forecast_schedule`（第 6 項）的註冊、啟用狀態、期望 cron 與下一次 tick 的結果（例如尚無模型時的略過原因）；此檢查唯讀，只評估排程函式，不啟動 run。發布排程未註冊或 cron 不符為 `FAIL`；已註冊但未開啟為 `WAIT`，因冷啟動期間首次訓練成功後才開啟。另檢查 `forecast_track_record_schedule`（第 7 項）的註冊、啟用狀態與期望 cron；未註冊、cron 不符或未開啟皆為 `FAIL`，比照擷取排程而非發布排程，因彙整不依賴模型，冷啟動時就與擷取排程一起開啟。`forecast_view_export_schedule`（第 8 項）比照預報實績排程：未註冊、cron 不符或未開啟皆為 `FAIL`。`--require-ready` 讓任一 `WAIT` 也回傳結束碼 `1`；`--task <task_id>` 保留擷取、發布、預報實績與匯出排程檢查，任務相關檢查只涵蓋該任務，未知任務為用法錯誤（結束碼 `2`）並列出已部署任務。操作步驟見 [冷啟動恢復指南](../how-to/recover-training-after-load-cold-start.md)。
