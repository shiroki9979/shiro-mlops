# Dagster 資產排程與觸發規格

> - Created: 2026-11-20
> - Last Updated: 2026-11-27

---

## 執行來源與 as_of

帶 as_of 的排程資產由 `src/shiro_mlops/pipelines/execution_origin.py` 把一次 run 解析成執行來源與 as_of，各資產只宣告沒有 tick 時怎麼做。目前採用的資產：`{task_id}__features` 與 `{task_id}__monitoring`（第 1 項，皆退回現在）、三個台電即時快照資產（第 2 項，退回現在）、`raw_taipower_load`（第 5 項，退回現在）、`issued_forecast`（第 6 項，拒絕）、`forecast_track_record`（第 7 項，退回現在）、`forecast_view_export`（第 8 項，退回現在；匯出排程不帶 tick，as_of 一律是 run 建立時刻）；其餘各項的 tick 來源見各項說明。

- **三種來源**：排程 tick 發起的 run、手動執行（含在 launchpad 手動啟動）、重新執行（Dagster UI 的 re-execute 等，以原 run 為 parent 建立的新 run）。`RetryPolicy` 的重試在同一 run 內進行、不產生新 run，沿用該 run 的來源與 as_of。
- **tick 標籤**：排程以 `tick_run_request` 產生 `RunRequest`：有 tick 時，`run_key` 與 run 標籤 `shiro_mlops/scheduled_tick` 皆為 tick 的台灣本地時間 ISO 字串（例如 `2026-11-20T10:25:00`）；以 `build_schedule_context()` 不帶時間評估時兩者都不帶，不拋錯。一個 run 只有一個 tick，job 內所有資產共用；資產不以設定欄位接收 tick。只用公開的 `RunRequest(tags=...)`，不讀 Dagster scheduler 的隱藏標籤 `.dagster/scheduled_execution_time`。
- **真偽判定**：tick 只在排程 daemon 為該 tick 發起的那個 run 才算數：run 必須同時帶 tick 標籤、`dagster/schedule_name`（Dagster 對排程評估產生的每個 run request 加上）與值等於 tick 標籤的 `dagster/run_key`（只有排程 daemon 發起 run 時才由 `run_key` 加上），且不帶重新執行標籤 `dagster/parent_run_id`、`dagster/root_run_id`。手動執行、在 launchpad 自填 tick 標籤（不帶 `dagster/schedule_name`）、重新執行（沿用原 run 的標籤，tick 標籤與排程名稱也一併沿用）一律視為沒有 tick。在 Dagster UI 的排程 tick 預覽（Preview tick result）按 Launch 發起的 run 也視為沒有 tick：預覽可選過去與未來各十個 tick，按下後只把排程評估產生的標籤（tick 標籤與排程名稱）複製到手動 run 上、不帶 `dagster/run_key`；若把它當成排程 run，會補發過去的預報、預先發布未來的預報，或把當下的台電即時值寫進過去的觀測 slot。
- **拒絕或退回現在**：資產宣告沒有 tick 時是「拒絕」或「退回現在」。拒絕時 run 以 `Failure` 結束，description 區分「沒有排程 tick」與「重新執行」。
- **「現在」**：run 的建立時刻（Dagster run 紀錄的建立時間），轉為台灣本地時間；不是每次嘗試的當下，因此同一 run 內的重試得到同一 as_of。
- **對齊**：module 只交出未取整的 as_of；十分鐘 slot 與整點的取整由各領域函式負責。
- **新增帶 as_of 的排程資產**：排程回傳 `tick_run_request(context)`（需要略過時另回傳 `SkipReason`）；資產以 `run_as_of(context, without_tick=...)` 取得 as_of，宣告 `WithoutTick.REFUSE` 或 `WithoutTick.FALL_BACK_TO_NOW`。不新增 tick 設定欄位，也不在資產或排程內自取現在時刻、自讀 tick 或 Dagster 的排程名稱與重新執行標籤。
- **邊界測試**：`tests/unit/test_pipelines_as_of_boundary.py` 掃描 `src/shiro_mlops/pipelines/`，在 `execution_origin.py` 以外抓到直接取現在時刻（`taiwan_now()`、`datetime.now()` 等）、讀取排程 tick（`scheduled_execution_time`）或讀取 tick、排程名稱、重新執行標籤時失敗。唯一例外是 `smoke_check.py`：它是操作人員在容器內執行的 CLI，不在 Dagster run 裡，以現在時刻當作 tick 評估各排程。

## 資產、job 與排程

1. **任務資產工廠（`pipelines/task_pipelines.py`）**：
   - **生成規則**：Dagster code location 載入時，依 `deployed_tasks()` 為每份任務設定（[ML 任務設定 §1](ml-tasks.md#1-任務設定-schemataskstask_idtoml)）產生下列定義；新增一份任務設定即新增一組，不需改動程式。名稱以 `__` 分隔任務 id 與後綴，資產 group 為 `task_id`。

     | 種類 | 名稱 | 內容 |
     | :--- | :--- | :--- |
     | 資產 | `{task_id}__features` | 經 runner `load_training_data` 讀取並套用最低累積，輸出 `training_table`（以目標序列與觀測天氣的時間軸聯集為主鍵序列化：`datetime`、`subject`、`load_mw` 與 `weather.fields`，保留負載缺漏小時的觀測天氣；`rows` metadata 為訓練表總列數）；資產依賴（`deps`）`raw_taipower_load` 與 `raw_cwa_station_observation`，但不執行它們 |
     | 資產 | `{task_id}__model` | 以 `training_data_from_table` 還原上游訓練表後經 `fit_task` 訓練，不再重讀資料庫；模型存入 `DATA_DIR/models/{task_id}/`，並寫入 MLflow（見下）。輸出 `task_id`、`metrics`、`run_id`、`model_version`、`model_path`、`training_rows`；materialization metadata 除各 metric 外，另記 `model_sha256`（剛保存的模型目錄雜湊，定義見 [ML 任務設定 §4](ml-tasks.md#4-模型存放tasksmodel_storepy)）與 `mlflow_model_version`（MLflow model version；MLflow 不可用、`run_id` 為 `local_run` 時為空值，`model_sha256` 照常記錄） |
     | 資產 | `{task_id}__monitoring` | 經 runner `monitor_task` 以有界查詢讀取有效逐時觀測數與 `as_of` 以前最新一列（僅 `source = 'regional_snapshot_sum'`），再由任務類型 `assess_health` 以任務設定 `[health]` 門檻判定；輸出 `task_id`、`status`（`HEALTHY`／`WARNING`）、`health_reason`、`metrics`、`training_rows`、`target_hours`（有效逐時目標觀測數）、`latest_target_time`、`latest_target_value`（目前任務的目標皆為逐時實際負載，單位 MW） |
     | job | `{task_id}__training_job` | selection 為 `{task_id}__features` 及其所有下游（model、monitoring，以及只掛在該任務的資產，例如 Feast 匯出） |
     | job | `{task_id}__monitoring_job` | selection 僅含 `{task_id}__monitoring`；model 輸出取自最近一次訓練的 I/O Manager 產物，不重跑讀取訓練歷史的 features |
     | 排程 | `{task_id}__training_schedule` | cron 取自 `[schedule].training`，時區 `Asia/Taipei`；只看最低累積，未達時以 `SkipReason` 揭露差距，不受模型狀態影響（見下方冷啟動階段） |
     | 排程 | `{task_id}__monitoring_schedule` | cron 取自 `[schedule].monitoring`，時區 `Asia/Taipei`；除最低累積外，另需訓練紀錄有模型（`{task_id}__model` 已有 materialization），不看模型目錄（見下方冷啟動階段） |

   - **邊界**：擷取資產（台電快照、逐時負載推算、CWA 觀測與預報）以資料來源為中心、跨任務共用，不隨任務生成；任務的兩個 job 皆不得選取任何擷取資產，也不得選取 `issued_forecast`（見第 6 項）、`forecast_track_record`（見第 7 項）或 `forecast_view_export`（見第 8 項）。資產只經 runner（[ML 任務設定 §3](ml-tasks.md#3-runnertasksrunnerpy)）取門檻、資料、訓練與監控結果。
   - **冷啟動階段（`pipelines/cold_start.py`）**：`read_cold_start` 從三個輸入判定任務的階段與原因：最低累積的結果（見下方「最低累積」）、模型目錄（`DATA_DIR/models/{task_id}/` 有沒有由模型存放安裝的模型，規則同 [ML 任務設定 §4](ml-tasks.md#4-模型存放tasksmodel_storepy) 的 `has_installed_model`）、訓練紀錄（`{task_id}__model` 有沒有 materialization）。只判斷兩邊有沒有模型：不載入模型、不比對雜湊（訓練先安裝模型目錄、再寫 materialization，比對雜湊會把每次訓練中間的空檔判成不一致）。五個階段為封閉集合，每個都帶原因：

     | 階段 | 條件 | 原因 |
     | :--- | :--- | :--- |
     | 舊列阻擋（`BLOCKED_BY_LEGACY_ROWS`） | 兩邊都沒有模型，最低累積被 `source IS NULL` 的舊列擋下 | 最低累積的原因 |
     | 累積中（`ACCUMULATING`） | 兩邊都沒有模型，有效逐時觀測未達最低累積 | 最低累積的原因 |
     | 待首次訓練（`AWAITING_FIRST_TRAINING`） | 兩邊都沒有模型，已達最低累積 | 最低累積的原因，並說明下一次 `{task_id}__training_job` 會訓練第一個模型 |
     | 已訓練（`TRAINED`） | 訓練紀錄與模型目錄都有模型 | 兩邊都有模型 |
     | 紀錄與目錄不一致（`RECORD_DIRECTORY_MISMATCH`） | 只有一邊有模型（例如刪除 `dagster_home` volume 但保留 `data/models/`，或相反） | 點名缺少模型的一邊，處理方式為執行一次 `{task_id}__training_job` |

     已有模型時，階段停在「已訓練」或「紀錄與目錄不一致」，即使最低累積之後又未通過（例如調高 `min_training_hours`，或舊列被寫回），因此階段不是單純的線性鏈。訓練、監控與發布排程「要不要執行、不執行的原因」都由此 module 給出，排程本身不查 materialization、模型目錄或最低累積；每個排程只看自己的資產實際會用到的那一邊。各排程也只讀自己需要的輸入：訓練排程以 `read_training_decision` 只查最低累積，讀不到訓練紀錄或模型目錄不影響訓練 tick；發布排程與發布資產以 `read_model_presence` 只讀訓練紀錄與模型目錄，不查負載資料表；監控排程以 `read_cold_start` 讀全部三個輸入。發布排程（第 6 項）只看模型目錄，不看最低累積，因此最低累積未通過時照常發布：

     | 模型狀態 | 訓練排程 | 監控排程 | 發布排程 |
     | :--- | :--- | :--- | :--- |
     | 最低累積未通過（不論模型狀態） | 以最低累積的原因略過 | 以最低累積的原因略過 | 依下列模型狀態，不看最低累積 |
     | 兩邊都沒有 | 執行 | 略過：`No {task_id}__model materialization yet; {task_id}__monitoring_schedule waits for the first successful {task_id}__training_job run.` | 略過：`No dynamic_horizon_forecast__model materialization yet; issued_forecast_schedule waits for the first successful training run.` |
     | 兩邊都有 | 執行 | 執行 | 執行 |
     | 只有訓練紀錄 | 執行 | 執行（監控資產從上次訓練的紀錄取 metrics，不讀模型目錄） | 以「紀錄與目錄不一致」的原因略過 |
     | 只有模型目錄 | 執行（重新訓練即不一致的處理方式） | 以「紀錄與目錄不一致」的原因略過 | 執行（發布資產從模型目錄載入模型），MLflow 附註留空 |

   - **排程 run_key 與 as_of**：兩個排程以 `tick_run_request` 把 tick 的台灣本地時間 ISO 字串同時作為 `run_key` 與 tick 標籤（[執行來源與 as_of](#執行來源與-as_of)），同一 tick 重複評估不重跑；無 tick 的手動評估兩者都不帶。`{task_id}__features` 與 `{task_id}__monitoring` 以 run 的 as_of 呼叫 runner，沒有 tick 時退回現在：排程 tick 發起的 run 為該 tick（例如動態視界預報每日 00:00 的訓練固定以 00:00 為 as_of，不因排隊或執行延遲而後移），手動執行與重新執行的 run 為 run 建立時刻；資產沒有 tick 設定欄位。訓練 job 內所有資產共用同一 run 的 as_of，因此訓練 job 裡的 monitoring 與 features 用同一時刻。兩個 job 目前沒有重試政策。
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
   - **來源 port**：三個資產的 fetch 皆由 Dagster resource 注入（`taipower_supply_demand_source`、`taipower_regional_supply_demand_source`、`taipower_unit_generation_source`），只回傳來源原始 payload；asset 以各來源 module 的 parse 函式轉為 typed 快照後 upsert。機組資產的輸出只含機組快照，完整回應只寫入資料庫的 batch header（[資料契約 §3](data-contracts.md#3-地端時序資料庫模型-timescaledb-hypertables) 第 8 項）。正式環境綁定 `Taipower*Client` HTTP adapter（端點取自 settings），測試綁定 fixture adapter。
   - **冪等性**：三個資產以 [執行來源與 as_of](#執行來源與-as_of) 取得同一個 run 的 as_of，宣告沒有 tick 時退回現在，再以 `floor_to_ten_minutes` 向下取整成 10 分鐘觀測 slot；adapter 不決定 slot，資產也沒有 tick 設定欄位。排程 run 寫入 tick 的 slot；手動 materialize、無 tick 的排程評估與重新執行的 run 都寫入 run 建立時刻的 slot，三個資產一定落在同一個 slot。重新執行不沿用原 tick：台電即時 API 只回傳當下的值，寫進原 tick 的 slot 會覆寫或補上一筆標錯時間的快照。全台快照以 `observed_at` 為鍵；區域快照以 `(observed_at, region)` 為鍵；機組快照以 `(observed_at, unit_type, unit_name)` 為鍵，同一次回應的 batch header 以 `observed_at` 為鍵。相同 slot 重跑時皆更新同一快照。
   - **資料完整度與失敗政策**：
     - 全台：`curr_load` 與 `curr_util_rate` 為必填欄位；缺少、無法解析，或 HTTP／重試最終失敗時，asset 必須失敗且不得寫入快照。預估尖峰、昨日尖峰與實際最高供電能力資料組可缺少，對應 typed 欄位保存為 `NULL`，完整來源回應仍保存於 `raw_payload`。
     - 區域：來源列缺少核心 `時間`、`區域` 或 `用電(萬瓩)`、或無法解析時，略過該列且不寫入該區域快照；`發電(萬瓩)` 可缺少並保存為 `NULL`。HTTP／重試最終失敗，或成功回應中無任何有效區域列時，asset 必須失敗且不得寫入。
     - 機組：來源列缺少 `機組類型` 或 `機組名稱` 時略過該列；`淨發電量(MW)` 為 `0.0` 時仍寫入；`N/A`／`-` 的發電量、裝置容量或容量比保存為 `NULL`；備註空白保存為 `NULL`。HTTP／重試最終失敗，或成功回應中無任何有效機組列時，asset 必須失敗且不得寫入。
3. **CWA 逐時測站觀測擷取工作**：
   - **排程**：`10 * * * *`（`Asia/Taipei`）；失敗時在同一 run 內最多重試三次，以三十秒起算指數退避（Dagster 依序等待 30／90／210 秒，約 5.5 分鐘內結束）；重試用盡時 run 必須失敗且不得改動既有資料。
   - **故障邊界**：使用獨立 job 與 schedule，不與台電即時快照、任務訓練或監控工作共用成敗狀態。
   - **來源 port**：觀測與預報資產皆由 `cwa_source` resource 注入來源；正式環境綁定 `CWAClient`（API key 取自 settings），其回傳已 parse 的 typed batch／release。
4. **CWA 鄉鎮預報版本擷取工作**：
   - **排程**：`40 * * * *`（`Asia/Taipei`）；每小時檢查 `F-D0047-089` 與 `F-D0047-091`，以 `(dataset_id, IssueTime, Update)` 去重；失敗時在同一 run 內最多重試三次，以三十秒起算指數退避；重試用盡時 run 必須失敗且不得改動既有預報版本。
   - **故障邊界**：使用獨立 job 與 schedule，不因觀測擷取或其他管線失敗而跳過當次預報版本。
5. **`hourly_actual_load_job`**：
   - **排程**：`5 * * * *`（`Asia/Taipei`）；以 `tick_run_request` 把 tick 同時作為 `run_key` 與 tick 標籤（[執行來源與 as_of](#執行來源與-as_of)），資產沒有設定欄位。無 tick 的手動排程評估兩者都不帶，run 以建立時刻為準。
   - **管線鏈路**：讀取 `raw_taipower_regional_supply_demand_snapshot`，依 [資料契約 §1](data-contracts.md#1-台電用電負載實體-taipower-load-schema) 推算已結束小時，以 `(time, subject)` upsert 至 `raw_taipower_load`，`subject` 為 `nationwide`；不呼叫任何台電外部 API。
   - **推算窗口**：最近 `HOURLY_LOAD_RECOMPUTE_HOURS`（預設 `3`）個已結束小時，並向前延伸至評估時刻前已存在的最後一個推算小時（`source = regional_snapshot_sum`）之後，使擷取中斷前已入庫、尚未推算的小時在排程恢復後補上；最多回溯 `HOURLY_LOAD_CATCHUP_MAX_HOURS`（預設 `168`）個小時，尚無推算小時時即回溯此上限。超出上限而未涵蓋的區間以 warning 記錄於 run log，改由 `scripts/rederive_hourly_actual_load.py` 補算。
   - **組合**：決定推算窗口、讀取窗內區域快照、推算與寫入由全台逐時實際負載 store（`src/shiro_mlops/data/hourly_actual_load_store.py` 的 `HourlyActualLoadStore.derive_scheduled`）負責，寫入列的 `source` 由 store 固定為 `regional_snapshot_sum`。資產只以 `run_as_of` 取得評估時刻，以 `HOURLY_LOAD_RECOMPUTE_HOURS`、`HOURLY_LOAD_CATCHUP_MAX_HOURS` 與 `HOURLY_LOAD_MIN_SAMPLES` 呼叫 store，再依回傳的推算窗口、未涵蓋區間、快照數與寫入小時數記錄 log 與 warning。
   - **冪等性**：評估時刻為 run 的 as_of，資產宣告沒有 tick 時退回現在（[執行來源與 as_of](#執行來源與-as_of)）：排程 tick 發起的 run 為該 tick，手動執行與重新執行的 run 為 run 建立時刻，同一 run 內的重試得到同一推算窗口。重新執行排程 run 時不沿用原 tick；追補窗口從最後一個推算小時之後接續，原 tick 應涵蓋的小時仍在窗口內，最多回溯 `HOURLY_LOAD_CATCHUP_MAX_HOURS`。重算同一小時得到相同結果；後到的有效樣本可使先前缺值的小時補上或更新平均值。
6. **`issued_forecast_job`（已發布預報，[ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md)）**：
   - **定義**：固定資產 `issued_forecast`、job `issued_forecast_job`、排程 `issued_forecast_schedule`，位於 `pipelines/issued_forecast.py`，不進任務資產工廠；只發布動態視界預報。排程預設停用，於首次訓練成功後開啟。
   - **發布結局**：資產取得發布時刻後呼叫 `pipelines/issuing.py` 的 `issue_forecast`，它回傳四種結局之一：`Issued`（已寫入）、`AlreadyIssued`（該發布時刻已有紀錄，不寫入）、`ModelUnavailable`（模型目錄沒有可發布的模型）、`ForecastUnavailable`（runner 無法產出預報）。資產只把結局轉成 materialization metadata 或 `Failure`，對應見下方「無法產出」與「冪等性」。排程與 `issue_forecast` 以同一個 `issuing_decision` 判斷有沒有模型可發布。
   - **排程**：`15 * * * *`（`Asia/Taipei`），排在逐時負載推算（:05）與觀測擷取（:10）之後。以 `tick_run_request` 把 tick 同時作為 `run_key` 與 tick 標籤（[執行來源與 as_of](#執行來源與-as_of)），資產沒有設定欄位。
   - **發布時刻**：發布時刻即排程 tick 時刻，也是預報的 `as_of`，不取整點（決策見 [#136](https://github.com/shiroki9979/shiro-mlops/issues/136)）。
   - **管線鏈路**：經 runner `predict_task`（[ML 任務設定 §3](ml-tasks.md#3-runnertasksrunnerpy)）以 H = 168 預報，降級與負載起點過舊規則照舊；以 `load_model_with_sha256` 在同一把鎖下取得載入的模型與其雜湊，經 `time_series_repo` resource 交出的已發布預報 store（`issued_forecast_store`）寫入 [資料契約 §3](data-contracts.md#3-地端時序資料庫模型-timescaledb-hypertables) 的 `issued_forecast` 與 `issued_forecast_step`。不讀模型健康檢查：`{task_id}__monitoring` 為 `WARNING` 時照常發布。已安裝的模型以不同於任務設定的輸入配方訓練時（`ModelRecipeMismatchError`，[ML 任務設定 §2](ml-tasks.md#2-任務類型介面taskstypes)），以 `Failure` 結束、不寫入，訊息列出不同的項目；排程照常觸發，直到重新訓練。
   - **資產依賴（`deps`）**：只有 `raw_taipower_load`、`raw_cwa_station_observation` 與 `raw_cwa_township_forecast`，但不執行它們；不依賴 `{task_id}__model`，因此任務 job 不會帶出發布（見第 1 項邊界）。`issued_forecast_job` 不選取任何擷取資產。
   - **只有定時發布才算**：資產宣告沒有 tick 時拒絕（[執行來源與 as_of](#執行來源與-as_of)），退回現在等於在 tick 以外的時刻補發。只有排程 tick 發起的 run 以該 tick 發布；手動 materialize、在 launchpad 自填 tick 標籤的 run、從排程 tick 預覽發起的 run，以及重新執行的 run 皆以 `Failure` 結束、不寫入，因此不補發。無 tick 的手動排程評估以 `SkipReason` 略過、不產生 run。隨需 `/predict` 不寫入。
   - **無法產出**：排程與資產都以第 1 項的 `read_model_presence` 判斷有沒有模型可發布，只看模型目錄、不查最低累積。模型目錄沒有由模型存放安裝的模型時，排程以 `SkipReason` 略過：兩邊都沒有模型時為尚無 `dynamic_horizon_forecast__model` materialization 的原因，只有訓練紀錄時為「紀錄與目錄不一致」的原因。只有模型目錄時（例如刪除 `dagster_home` volume 但保留 `data/models/`）照常發布，MLflow 附註（`mlflow_model_version`）依 [資料契約 §3](data-contracts.md#3-地端時序資料庫模型-timescaledb-hypertables) 的雜湊比對規則留空。模型目錄在 tick 之後、run 載入之前消失時，資產以 `Failure` 結束、description 與上述排程的略過原因相同（說明沒有模型，或紀錄與目錄不一致）並附 `issued_at` metadata，不寫入。負載起點過舊、天氣不可用、歷史不足（`TaskUnavailableError`）時，資產以 `Failure` 結束、description 為 runner 的原因並附 `issued_at` metadata，不寫入。
   - **不設重試政策**：`issued_forecast` 資產與 `issued_forecast_job` 皆無重試政策；重新執行的 run 不寫入（見上）。理由見 [ADR-0013 §2.1](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md#21-已發布預報) 的不補發與 [#136](https://github.com/shiroki9979/shiro-mlops/issues/136)。
   - **冪等性**：同一發布時刻已有紀錄（例如 commit 後崩潰被重跑）時不預報、不寫入、不覆寫，資產成功並以 metadata `already_issued = true` 標示；預報完成後寫入時才發現已有紀錄者，同樣不覆寫並以 `already_issued = true` 標示。新寫入時 metadata 另記 `load_anchor`、`status`、`model_sha256` 與步數。
7. **`forecast_track_record`（預報實績，[ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md)）**：
   - **定義**：固定資產 `forecast_track_record`，位於 `pipelines/forecast_track_record.py`，不進任務資產工廠。資產依賴（`deps`）`issued_forecast` 與 `raw_taipower_load`，但不執行它們；任務的兩個 job 與 `issued_forecast_job` 皆不選取它。
   - **排程**：job `forecast_track_record_job` 與排程 `forecast_track_record_schedule` 同位於 `pipelines/forecast_track_record.py`。排程為 `25 * * * *`（`Asia/Taipei`），排在發布（:15）之後；以 `tick_run_request` 把 tick 同時作為 `run_key` 與 tick 標籤（[執行來源與 as_of](#執行來源與-as_of)），資產沒有設定欄位。無 tick 的手動排程評估兩者都不帶，run 以建立時刻為準。job 只選取 `forecast_track_record`，不選取任何擷取資產，也不選取 `issued_forecast`，因此發布失敗或略過時照常彙整。排程預設停用，冷啟動時與擷取排程一起開啟，不需等待首次訓練。
   - **重試政策**：`forecast_track_record_job` 失敗時在同一 run 內最多重試兩次，每次間隔六十秒，用盡後仍遠早於下一個 tick。彙整只讀資料庫、從頭重算且不保存歷次結果，可吸收短暫的資料庫中斷。重試在同一 run 內、沿用同一 as_of，排程觸發與手動執行的 run 都得到同一統計窗。`issued_forecast` 刻意不重試（第 6 項），是因為重試會沿用原 tick 為預報的 `as_of` 卻讀到其後入庫的負載；彙整的統計截至時刻只界定統計窗，讀到其後入庫的資料不違反 point-in-time，不受此限。
   - **統計截至時刻 E**：run 的 as_of 取整點。資產宣告沒有 tick 時退回現在（[執行來源與 as_of](#執行來源與-as_of)）：排程 tick 發起的 run 為該 tick，手動執行與重新執行的 run 為 run 建立時刻。重新執行排程 run 時不沿用原 tick，否則會以較早的截至時刻覆蓋最新一次 materialization，讓下一次預報檢視匯出退回舊的統計截至時刻。
   - **統計窗**：目標小時 ∈ [E − 720h, E)，以目標小時判斷，與發布時刻無關；窗開始前發布、目標小時落在窗內的步數也計入。
   - **配對與計入**：提前時數 = ⌈(目標小時 − 發布時刻) / 1h⌉，不大於 0 的步數不計入，例如 10:15 發布時 10:00 不計入、11:00 為提前 1、隔天 10:00 為提前 24。只配對有有效逐時觀測的目標小時，即 `raw_taipower_load` 中 `subject = 'nationwide'`、`source = 'regional_snapshot_sum'` 的列。降級預報照常計入。
   - **有界查詢**：資產經 `time_series_repo` 的 `forecast_track_record_store` 取得配對讀取。`data/forecast_track_record.py` 的 `ForecastTrackRecordStore.fetch_pairs` 以一條 SQL join，依目標小時把已發布預報步數對上窗內的有效逐時觀測，只回傳配對成功的列（發布時刻、目標小時、預測值、實際值）。只讀目標小時在窗內、發布時刻晚於窗起點前 168 小時的步數（步數最遠落在負載起點後 168 小時，而負載起點早於發布時刻），不讀整段歷史；提前時數與 MAPE／MAE 等彙總在 Python 計算。
   - **累積天數**：窗內有配對的目標小時，取台灣日期去重後的天數，最多 31。
   - **重算**：每次都從頭重算、不保存歷次結果，因此允許手動執行、重試與重新執行，事後推算補上的小時在下次彙整自然計入。尚無已發布預報時照常成功，累積天數為 0。
   - **輸出與 metadata**：輸出格式見 [資料契約 §5.1](data-contracts.md#51-預報實績-forecast_track_record)。materialization metadata 記 `cutoff`（統計截至時刻）、`accumulated_days`、`window_pairs`（窗內總配對數）與 `lead_24_pairs`（窗內提前 24 的配對數，未滿 7 天也記），只在 Dagster UI 可見，不匯出。
8. **`forecast_view_export`（預報檢視匯出，[ADR-0015](../adr/0015-publish-forecast-view-as-static-precomputed-output.md)）**：
   - **定義**：固定資產 `forecast_view_export`、job `forecast_view_export_job` 與排程 `forecast_view_export_schedule`，位於 `pipelines/forecast_view_export.py`，不進任務資產工廠。以 input 讀取最近一次 `forecast_track_record` 的 artifact，另以資產依賴（`deps`）連到 `issued_forecast`，兩者都不執行；最新已發布預報由 `time_series_repo` resource 交出的已發布預報 store（`issued_forecast_store`，`src/shiro_mlops/data/issued_forecast_repository.py` 的 `IssuedForecastRepository`）以 `fetch_latest` 讀取。任務的兩個 job、`issued_forecast_job` 與 `forecast_track_record_job` 皆不選取它。
   - **排程**：`35 * * * *`（`Asia/Taipei`），排在發布（:15）與預報實績彙整（:25，含重試約於 :28 前結束）之後。tick 轉為台灣本地時間 ISO 字串作為 `run_key`，刻意不帶 tick 標籤與資產設定：匯出的是執行當下最新的已發布預報與預報實績，與 tick 時刻無關。job 只選取 `forecast_view_export`，因此彙整失敗或略過時照常匯出最新已發布預報，預報實績則沿用上一次成功彙整的統計截至時刻。排程預設停用，冷啟動時與 `forecast_track_record_schedule` 一起開啟，不需等待首次訓練。
   - **先寫地端，再上傳**：兩份 JSON（格式見 [資料契約 §6](data-contracts.md#6-預報檢視公開-jsonpublished)）先寫入 `DATA_DIR/published/`，每個檔案先寫暫存檔再以 rename 替換，Nginx 不會讀到寫一半的檔案；全部寫完後，有設定 `FORECAST_VIEW_S3_BUCKET` 時再以 `PutObject` 上傳同樣的位元組到 bucket 的 `published/` prefix（`Content-Type: application/json`，不設 `Cache-Control`）。未設定 bucket 時不建立 S3 client。上傳設定見 [預報檢視託管 §1](forecast-view-hosting.md#1-s3-配置與寫入權限)。
   - **失敗與重試**：上傳失敗時 run 失敗、在地端 Dagster 執行紀錄可見，地端目錄已是本次內容。`forecast_view_export_job` 失敗時在同一 run 內最多重試兩次、每次間隔六十秒；匯出覆寫固定檔名，重試、手動執行與重新執行皆安全。從未 materialize 過 `forecast_track_record` 時（全新環境），input 為空，匯出照常寫出並上傳最新已發布預報，預報實績寫出累積 0 天、統計截至時刻為匯出 run 建立時刻整點的空狀態（資產經 [執行來源與 as_of](#執行來源與-as_of) 宣告退回現在；匯出排程不帶 tick，排程、手動與重新執行的 run 皆以 run 建立時刻為準，同一 run 內的重試得到同一截至時刻）（[資料契約 §6.2](data-contracts.md#62-預報實績-forecast_track_recordjson)）。曾 materialize 過但 artifact 遺失時，input 讀取失敗，run 以錯誤結束，不當成全新環境。
   - **尚無已發布預報**：照常成功，最新已發布預報輸出空狀態（[資料契約 §6.1](data-contracts.md#61-最新已發布預報-latest_issued_forecastjson)）。
   - **metadata**：`issued_at`（無已發布預報時為空字串）、`published_steps`、`cutoff`、`accumulated_days`、`local_dir` 與 `uploaded_to_s3`。
9. **CWA 消費邊界**：
   - 外部 CWA API 僅由兩個 ingestion jobs 呼叫；模型訓練與線上預測一律讀取 canonical TimescaleDB tables，不得在缺資料時繞過 ingestion 邊界直接呼叫 CWA。
   - 三個任務目前只使用氣象代表點 `Taipei`（測站與預報區見 [資料契約 §2](data-contracts.md#2-中央氣象署資料實體-cwa-weather-schemas) 目錄）。任務設定可依 [ML 任務設定 §1](ml-tasks.md#1-任務設定-schemataskstask_idtoml) 列出多個加權代表點（ADR-0012），是否採用由 TICKET-303 的滾動起點回測判定。
10. **本機冷啟動**：
    - 空資料庫啟動後，台電即時快照排程須先累積區域快照，且 `hourly_actual_load_job` 產出的有效逐時觀測達訓練最低累積；之後由操作人員依序 materialize CWA 觀測資產、CWA 預報資產與訓練工作；完成前 `/ready` 回傳 HTTP 503。
    - 不新增一次性 bootstrap sensor，也不等待每日訓練排程自然觸發。
    - 操作人員以 `python -m shiro_mlops.pipelines.smoke_check`（`make smoke-check`）在 Dagster 容器內檢查排程註冊與啟用狀態（任務排程的期望 cron 由任務設定推導）、各任務訓練與監控 job 的 selection 邊界，以及每個任務的累積進度（`{task_id} load accumulation`）、新鮮度（`{task_id} load freshness`）、冷啟動階段（`{task_id} model`）與兩個任務排程下一次 tick 的結果，並檢查 `issued_forecast_schedule`（第 6 項）的註冊、啟用狀態、期望 cron 與下一次 tick 的結果（例如尚無模型時的略過原因）；此檢查唯讀，只評估排程函式，不啟動 run。發布排程未註冊或 cron 不符為 `FAIL`；已註冊但未開啟為 `WAIT`，因冷啟動期間首次訓練成功後才開啟。另檢查 `forecast_track_record_schedule`（第 7 項）的註冊、啟用狀態與期望 cron；未註冊、cron 不符或未開啟皆為 `FAIL`，比照擷取排程而非發布排程，因彙整不依賴模型，冷啟動時就與擷取排程一起開啟。`forecast_view_export_schedule`（第 8 項）比照預報實績排程：未註冊、cron 不符或未開啟皆為 `FAIL`。`{task_id} model` 讀第 1 項的冷啟動階段，與排程讀的是同一個判定，訊息為階段名稱加上階段原因：兩邊都沒有模型的三個階段為 `WAIT`，「已訓練」為 `PASS`，「紀錄與目錄不一致」為 `FAIL`（不需 `--require-ready` 即讓結束碼為 `1`），原因點名缺少的一邊與處理方式。讀不到 TimescaleDB 時，該任務的累積、新鮮度、冷啟動階段與兩個 tick 皆為 `FAIL`；只讀不到訓練紀錄或模型目錄時只有冷啟動階段那一行為 `FAIL`；兩者都不中斷其餘檢查。`--require-ready` 讓任一 `WAIT` 也回傳結束碼 `1`；`--task <task_id>` 保留擷取、發布、預報實績與匯出排程檢查，任務相關檢查只涵蓋該任務，未知任務為用法錯誤（結束碼 `2`）並列出已部署任務。操作步驟見 [冷啟動恢復指南](../how-to/recover-training-after-load-cold-start.md)。
