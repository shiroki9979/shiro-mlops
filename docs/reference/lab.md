# 研究空間（`lab/`）介面與報告契約

> - Created: 2026-11-20
> - Last Updated: 2026-11-28

---

> 依 [ADR-0011](../adr/0011-co-locate-lab-workspace-with-unidirectional-dependency.md)。程式位於 `lab/`，相依方向固定為 `lab` → `shiro_mlops`；操作步驟見 [如何執行一次 lab 研究](../how-to/run-lab-study.md)。

§1–§5 描述現行行為。§6 是 M11 的契約草案，尚未實作。

## 1. 快照（`lab/snapshot.py`）

| 介面 | 行為 |
| :--- | :--- |
| `write_snapshot(task, runtime, as_of, *, variant=None, snapshots_dir) -> Path` | 以 `load_training_data` + `training_table` 凍結訓練表，並於 parquet 記錄 `task.weather` 的代表點、權重與欄位；目標檔已存在時拋 `FileExistsError` 且不改動原檔；`as_of` 晚於現在時拋 `ValueError`（快照不可重寫，以未來時刻命名的檔案內容只到當下）；先完整寫入同目錄的暫存檔再以 hard link 放到定位，寫入中斷不會在目標路徑留下殘缺檔，兩次同時凍結同一快照時後完成者拋 `FileExistsError`；`TaskNotReady` 原樣拋出 |
| `read_snapshot(task, as_of, *, variant=None, snapshots_dir) -> TrainingData` | 讀回 parquet 後以 `training_data_from_table` 還原；快照記錄的天氣與 `task.weather` 不同時拋 `SnapshotWeatherMismatchError`；未記錄天氣的舊快照不檢查 |
| `snapshot_path(task, as_of, *, variant=None, snapshots_dir) -> Path` | 無 `variant` 時回傳 `<snapshots_dir>/<task_id>/<as_of>.parquet`，有 `variant` 時回傳 `<snapshots_dir>/<task_id>/<variant>/<as_of>.parquet`；`variant` 限小寫英數與連字號，否則拋 `ValueError`；`as_of` 一律換算為 Asia/Taipei 無時區時間 |

快照即訓練當下讀取的資料：任務設定 `policies.max_training_hours` 時，快照同樣只含訓練窗內的歷史，CLI 沒有移除上限的選項（凍結更長歷史的步驟見[如何執行一次 lab 研究](../how-to/run-lab-study.md#需要比訓練窗更長的歷史時)）。

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

- **起點語意**：起點為最後一筆已知實際負載的整點，預報目標為 `origin + 1h .. origin + horizon_hours`（`target_hours(origin, horizon_hours)`）。`origins` 正規化後不得重複，重複時拋 `ValueError`：重複的起點會在每項指標重複計入，`predictions` 卻只保留一筆。
- **訓練**：負載與氣象皆截斷為 `datetime <= origin`，`validation_start = origin + 1h`（驗證集為空）。
- **預報**：`PredictionData` 由預測輸入關卡（`admit_prediction_inputs`，[ML 任務設定 §2](ml-tasks.md#2-任務類型介面taskstypes)）建構，與 serving 相同：`anchor = origin`，`load_history` 只含 `(origin - lookback_hours, origin]` 的負載（含起點當小時）；`weather` 為目標時段的完整逐時軸，由回測以正式的觀測氣象對齊規則（2 小時內向後對齊）填入後交給關卡。
- **起點有效性**：每個起點須同時滿足下列條件，任一不合格拋 `OriginRejectedError`（`ValueError` 子類別，`check` 屬性為條件名稱：`minimum history`、`lookback load completeness`、`horizon weather completeness`、`horizon load completeness`）並指出起點與條件；關卡的拒絕以 `raise ValueError(...) from error` 包裝，原例外保留於 `__cause__`；訊息含關卡的拒絕訊息，第 2 項另附 lookback 內第一個缺負載的小時（`first missing: ...`），第 3 項的天氣部分由關卡訊息指出第一個缺值的目標小時：
  1. `datetime <= origin` 的有效負載小時數達 `min_history_hours`（預設取任務設定 `policies.min_training_hours`）。由回測判定。
  2. 任務類型 `history_coverage` 要求的 lookback 負載完整；遞迴回歸即 `(origin - lookback_hours, origin]` 的逐時負載完整（含起點當小時）。由預測輸入關卡判定，回測與 serving 接受的起點一致。
  3. 目標時段的實際負載有值（由回測判定），且對齊後觀測氣象的 `weather.fields` 皆有值（由預測輸入關卡判定）。

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
| `screen_origins(task, data, horizon_hours, *, min_history_hours=None)` | 以上述三項起點有效性條件（含預測輸入關卡）逐一檢查快照內每個整點，回傳 `OriginScreening`：`eligible` 為 `rolling_origin_backtest` 會接受的全部起點，`rejected` 為其餘整點的 `RejectedOrigin(origin, check, reason)`，`check` 為第一個不合格的條件 |
| `eligible_origins(task, data, horizon_hours, *, min_history_hours=None)` | `screen_origins(...).eligible` |
| `origin_runs(origins)` | 將排序後的起點分組為連續整點區間 `(first, last)` |
| `split_search_and_eval_origins(eligible, *, horizon_hours, eval_calendar_days, hour_step)` | 只取整點為 `hour_step` 倍數的起點；最後 `eval_calendar_days` 個日曆日為評估起點，搜尋起點為 `<= 第一個評估起點 - horizon_hours` 者，並以 `verify_non_overlapping_target_windows` 驗證；沒有可用的評估或搜尋起點，或 `hour_step` 不在 1–24、`eval_calendar_days`、`horizon_hours` 小於 1 時拋 `ValueError` |
| `training_row_count(task, data, origin)` | 遞迴回歸任務在 `origin` 截斷後實際訓練的列數（缺任一 lag 或天氣的列已剔除），用於揭露加權天氣嚴格缺值的訓練列損失 |

CLI：`uv run --package lab python -m lab.origins <task_id> --as-of <ISO> [--variant <name> --reference-points ... --weights ...] [--horizon-hours 24] [--eval-days 7] [--hour-step 6] [--explain]`，輸出合格起點數、日曆日數、連續區間、建議的搜尋／評估切分，以及評估起點是否涵蓋 `--eval-days` 個日曆日（`sufficient: yes|no`）。`--explain` 另將被拒絕的起點依連續整點與 `check` 分組，每組輸出 `rejected: <first> .. <last> (<n> h): <check>` 與該組最後一個起點的拒絕原因（`latest reason:`）。

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

## 6. M11 契約草案（尚未實作）

本節是 M11 的目標契約，依 [ADR-0018](../adr/0018-access-research-data-through-data-freezes-and-knowledge-time.md)、[ADR-0019](../adr/0019-serve-models-by-declaration-with-platform-owned-inference.md) 與 [ADR-0020](../adr/0020-hand-off-trained-models-and-pin-the-serving-model.md)。現行行為仍以 §1–§5 與 [ML 任務 reference](ml-tasks.md) 為準。

- **名稱是草案**：函式、檔名、資料表、欄位與規則代碼的名稱可以在實作票調整，ADR 的決策與 [ADR-0020 §5](../adr/0020-hand-off-trained-models-and-pin-the-serving-model.md#5-notes) 的英文命名結論不變。
- **標「提議」的項目**尚未經設計討論定案，由對應的實作票確認；其餘內容都出自 ADR。
- **落地**：每張實作票在同一個 PR 把它實作的部分搬到 §6.11 所列的 reference，並從本節刪除；本節清空時 M11 的契約即全部落地。

### 6.1 凍結資料與知悉時間

- **凍結**：`src/` 的唯讀 CLI（提議：`uv run python -m shiro_mlops.freeze`），不接受參數，凍結時刻是執行當下。輸出 `data/lab/freezes/<凍結時刻>.sqlite` 與同名的清單檔；目標已存在時拋 `FileExistsError`。
- **清單**：凍結時刻、git revision、schema 遷移版本、各表列數、檔案 SHA-256、被排除的表與欄位。
- **範圍**：見 [ADR-0018 §2.2](../adr/0018-access-research-data-through-data-freezes-and-knowledge-time.md#22-凍結資料)；擴充範圍以修改清單的 PR 進行。
- **讀取**：`open_freeze(path) -> TaskRuntime`，以唯讀模式開啟並依清單驗證 SHA-256。`lab/` 不得以其他方式建構 repository 或讀取資料庫連線設定。
- **知悉時間**：`fetch_latest_load`、`fetch_load_range`、`fetch_cwa_forecast_rows`、`fetch_cwa_station_observations` 加上必填的 `known_by`，篩選 `created_at <= known_by`。`check_task_ready`、`predict_task`、`resolve_weather` 傳 `known_by=as_of`；`load_training_data` 不篩。
- **取代 §1**：`write_snapshot`、`read_snapshot`、`snapshot_path`、`variant` 與 `lab.snapshot` CLI 移除；代表點與權重改為讀取時的研究變數，§1.1 的權重計算改讀凍結資料。

### 6.2 標準回測

取代 §2 的起點語意與「氣象已知」聲明。

| 項目 | 標準模式 | 「氣象已知」模式 |
| :--- | :--- | :--- |
| 起點 | 模擬的發布時刻 T，對齊已發布預報的排程整點 | 同左 |
| 負載起點 | `known_by=T` 下最新已知的小時 | 同左 |
| 天氣 | 照 serving 規則：預報版本、預報版本回退、降級 | 觀測天氣 |
| 提前時數 | 從 T 起算 | 同左 |
| 用途 | 研究報告的回測結果、評估閘門 | 只作診斷，報告須標明模式 |

`BacktestReport` 新增每個起點的預報運行狀態與回測模式。標準模式可用的起點限於氣象署預報開始入庫之後。研究報告（§5）的「快照」段與重現紀錄的「快照」欄改記凍結資料的 SHA-256 與訓練截止。

### 6.3 成品與宣告

成品是一個目錄：一份宣告檔（提議：`declaration.json`，取代現行的 `metadata.json`）加上任務類型的原生模型檔。成品的身分是模型目錄的 SHA-256（現行 `model_directory_sha256` 的定義）。

| 節 | 內容（鍵名為提議） | 規則 |
| :--- | :--- | :--- |
| 1. 身分 | `format_version`、`task_id`、`output_contract`、`task_type` | 成品綁定具體的 ML 任務，不能用於另一個輸出契約相同的任務 |
| 2. 特徵配方 | `features`：特徵種類與參數的清單 | 只能引用任務類型能解譯的種類；估計器超參數不在配方裡 |
| 3. 輸入 | `inputs`：序列、天氣欄位、氣象代表點與權重、天氣模式（`forecast`／`observed`） | 只能引用輸入目錄的項目 |
| 4. 任務類型參數 | `task_type_params` | schema 由任務類型定義；只放模型的操作點，例如預警機率門檻、異常門檻分位數 |
| 5. 最大時程 | `max_horizon_hours` | 不得短於輸出契約承諾的範圍 |
| 6. 訓練截止 | `training_cutoff` | 由寫入函式取訓練資料的最後一個目標小時，不由呼叫端傳入 |
| 7. 出處 | `provenance.origin`：出處種類，`platform` 或 `handoff` | 見下 |

- **研究出處**（`origin = "handoff"`）：凍結資料的 SHA-256 與凍結時刻、`source_revision`（commit SHA）、研究主題目錄 `lab/<YYYY-MM-DD>-<topic>/`。訓練截止不得晚於凍結時刻。
- **平台出處**（`origin = "platform"`）：訓練的 `as_of` 與平台程式的 commit。提議：commit 取自最新一筆工作樹更新紀錄（§6.8），因為程式改由工作樹執行，映像不再代表程式版本。
- **不宣告的項目**：lookback 與 `history_coverage` 由任務類型從配方推出。高負載門檻的定義屬於輸出契約，宣告不能改。
- **寫入函式**：格式的寫入與讀取都在 `src/`。工作樹有未提交的變更時，寫入函式拒絕寫出 `handoff` 出處的成品。只能靠釘選上線的任務類型，訓練程式放在 `lab/` 的常設模組（與 `lab/backtest.py` 同層，受 `lab/tests` 保護），呼叫 `src/` 的特徵程式與寫入函式。
- **三份清單**：特徵詞彙、輸入目錄、輸出契約各是 `src/` 的具名清單，內容與「只增不改」的規則見[三層形狀契約說明](../explanation/three-layer-handoff-shape-contract.md)。

### 6.4 可服務檢查

`check_servability(directory, task) -> ServabilityReport`，`src/` 的純函式。`lab/` 交付前呼叫它作為預檢；平台對交付包、每次平台訓練的結果、退回的目標，以及 API 啟動與熱替換時的現役模型執行它，只有平台的結果算數。報告同時有 JSON 與人看的文字，每條違規帶規則代碼、宣告中的路徑與說明。

分三段，前一段有違規就不進下一段；靜態檢查一次列出全部違規。

| 段 | 規則代碼（提議） | 違規情形 |
| :--- | :--- | :--- |
| 靜態 | `servability-sha256-mismatch` | 目錄雜湊與預期值不符；不符時不解析任何檔案內容 |
| 靜態 | `servability-file-not-allowed` | 任務類型的檔案白名單以外的檔案、子目錄或符號連結 |
| 靜態 | `servability-size-exceeded` | 總大小超過上限（提議 200 MB）；壓縮格式以解壓後的大小計 |
| 靜態 | `servability-declaration-schema` | 宣告不符合它的 `format_version` 的 schema，或 `format_version` 不受支援 |
| 靜態 | `servability-task-mismatch` | 宣告的 `task_id` 不是受檢的 ML 任務 |
| 靜態 | `servability-task-type-unregistered` | 任務類型未註冊 |
| 靜態 | `servability-output-contract-mismatch` | 宣告的輸出契約與任務設定不同，或任務類型不能產出它 |
| 靜態 | `servability-feature-kind-unsupported` | 配方引用了任務類型不能解譯的特徵種類 |
| 靜態 | `servability-input-not-in-catalog` | 輸入宣告引用了輸入目錄以外的項目 |
| 靜態 | `servability-task-type-params-schema` | 任務類型參數不符合任務類型的 schema |
| 靜態 | `servability-horizon-too-short` | 最大時程短於輸出契約承諾的範圍 |
| 靜態 | `servability-training-cutoff-after-freeze` | 訓練截止晚於凍結時刻 |
| 靜態 | `servability-source-revision-not-on-dev` | 交付紀錄的祖先檢查未通過；只有平台的正式檢查會判，預檢不判 |
| 載入 | `servability-load-failed` | 任務類型的推論端無法載入 |
| 試推論 | `servability-inference-failed` | 以合成輸入經預測輸入關卡預測時拋出例外 |
| 試推論 | `servability-output-shape` | 列數不等於時程、有缺值或型別不符 |
| 試推論 | `servability-output-field-not-in-contract` | 產出了輸出契約以外的欄位 |
| 試推論 | `servability-nondeterministic` | 同一輸入兩次預測的結果不同 |

試推論的合成輸入由 `src/` 依成品推導出的輸入需求生成，不用真實資料。

**信任邊界的強制**（[ADR-0020 §2.7](../adr/0020-hand-off-trained-models-and-pin-the-serving-model.md#27-信任邊界不載入可執行格式)）：

- 允許的載入呼叫：`json.loads`、`np.load(..., allow_pickle=False)`、`lgb.Booster(model_file=...)`。新格式隨任務類型的 PR 加進這份清單、[ML 任務 reference](ml-tasks.md) 的格式清單與黃金 fixture。
- 靜態測試以 AST 限定 `src/shiro_mlops/tasks/types/` 只能經允許清單讀檔，並攔下 `src/` 使用 MLflow flavor 的 `log_model`／`load_model`。
- 執行期測試在載入期間以 `sys.addaudithook` 攔截 `pickle.find_class`。兩道測試都不掃 `lab/`。
- 現行 `load_model_with_sha256` 先解析後算雜湊，改為在同一把 shared lock 內先比對雜湊再解析。

### 6.5 評估閘門

評分器在 `src/`，每個輸出契約一個；閘門、標準回測（§6.2）與監控共用。

| 輸出契約 | 核心指標 | naive 基準 |
| :--- | :--- | :--- |
| 負載曲線 | 以每小時一次的模擬發布時刻為起點，提前 1–168 小時各算一個 MAPE，再等權平均 | 目標小時前 168 小時的實際負載 |
| 高負載預警 | 判定（不用機率）的 F1；標籤依契約的高負載門檻（錨點前 28 日的 P90）產生 | 一週前同一小時是否高負載 |
| 異常旗標 | 乾淨窗的誤報率不超過上限為必要條件，符合時比三種合成異常的平均召回率 | 完全不標記 |

- **對手**：平台訓練的結果比目前的平台模型；交付包比目前的現役模型；沒有對手時比 naive 基準。有對手時 naive 基準的分數仍列在報告裡，不參與判定。
- **評估窗**：起點晚於雙方訓練截止中較晚者、目標小時已有實際值，只取最近 14 天；每個提前時數至少要有 7 天的配對，不足判 `inconclusive`。輸入以 `known_by=T` 照標準模式取用。
- **共同起點與可用率**：核心指標只在雙方都通過預測輸入關卡的起點上計算；候選模型通過關卡的起點比例低於對手即落敗。雙方被拒的起點都列在報告裡。
- **勝出**：平台訓練的結果在相對容忍幅度內即勝出（任務設定 `[gate]`，預設 5%），打平選較新的；交付包必須嚴格優於對手。
- **判定值**：`passed`、`failed`、`inconclusive`。`inconclusive` 由每日排程重評，第一次有足夠資料的評估即為終局；`failed` 是終局。
- **鍵**：判定以候選成品的 SHA-256 為鍵，相同位元組重新交付時沿用既有判定。`passed` 只在判定時的對手仍是目前要取代的對象時有效。
- **平台訓練**：驗證窗固定 14 天，取代 `policies.validation_fraction`。可服務檢查未通過算 run 失敗；`failed` 與 `inconclusive` 不算 run 失敗，`{task_id}__model` 的 metadata 與 MLflow 記下判定、雙方分數與評估窗。
- **lab 預覽**：`lab/` 可以用 `open_freeze` 的 runtime 在凍結資料上執行同一個評分器，對手由研究者指定；預覽不算判定。提議：對手成品以 `src/` 的唯讀載入函式依 SHA 從平台存放區取得，SHA 由 `handoff status` 查出，不複製、也不讓 `lab/` 讀資料庫。

### 6.6 交付、存放與保留

主機上的 CLI（提議：`uv run python -m shiro_mlops.handoff <子命令>`）：

| 子命令 | 行為 |
| :--- | :--- |
| `submit <dir>` | fetch 後檢查宣告的 `source_revision` 是 `origin/dev` 的祖先；把成品複製進存放區並重新雜湊；寫一筆交付紀錄，記下祖先檢查的結果。可服務檢查與閘門不在這個指令裡執行 |
| `status <sha>` | 印出人看的報告並輸出 JSON：可服務檢查的違規、閘門判定、雙方核心指標、評估窗、naive 基準、雙方被拒的起點、是否曾經生效。研究者把報告貼進釘選的 PR |
| `delete <sha>` | 只刪除從未生效、而且不是待定的交付包；其餘情況拒絕 |

評估由 Dagster sensor 撿起尚未評估的交付，在它啟動的 run 裡先做可服務檢查、再跑閘門；API 不解析沒有生效紀錄的成品。run 的逾時靠 run monitoring（[GitHub #426](https://github.com/shiroki9979/shiro-mlops/issues/426)）。

| 成品 | 位置 | 保留 |
| :--- | :--- | :--- |
| 交付包 | `DATA_DIR/handoffs/<task_id>/<sha256>/` | 曾經生效過的永久保留，連同它引用的凍結資料；待定的保留；其餘只能以 `delete` 刪除 |
| 平台模型 | `DATA_DIR/models/<task_id>/<sha256>/` | 目前的平台模型與被釘選的那一份不刪；曾經是現役模型的，不再服務滿 30 天後自動清理；從未服務過的，被取代時立即刪除 |

提議（由實作票確認）：

- **凍結資料不搬運**：凍結檔留在主機的 `DATA_DIR/lab/freezes/`。`submit` 確認被引用的凍結檔在那裡而且 SHA-256 相符，否則拒絕。前提是凍結 CLI 一律寫進主機的 `DATA_DIR`，而不是連結工作樹自己的 `data/`；連結工作樹在 PR 合併後會被移除。
- **凍結資料的刪除**：提供明確的刪除指令，被任何保留中的交付包引用的凍結檔拒絕刪除。
- **判定與報告全部保留**：它們是資料庫的 append-only 列，不清理。
- **平台模型的清理**：每日一次的 Dagster job 依生效紀錄執行，刪除前確認該 SHA 不是目前的平台模型、現役模型或期望狀態指到的 SHA。
- **既有模型目錄的搬遷**：既有模型接軌時，在模型存放的 exclusive lock 內把 `DATA_DIR/models/<task_id>/` 搬成 `models/<task_id>/<sha256>/`。接軌只登記已是新成品格式的模型；仍是舊格式的任務視為冷啟動，第一次以新格式訓練的結果和 naive 基準比。
- **新相依**：新任務類型的套件進根 `pyproject.toml` 的正式相依與 `uv.lock`；相依雜湊改變時由主機更新指令重建映像。API 與 Dagster 的相依在 M11 不拆開，因為兩邊都要載入同一批成品。

### 6.7 任務設定與期望狀態

兩個目錄都在 repo 根目錄，由同一個指向 repo 根目錄的設定項解析（預設為相對路徑，compose 設為 `/workspace`）。

`tasks/<task_id>.toml`（重啟才生效）：

| 欄位 | 規則 |
| :--- | :--- |
| `task_id`、`subject`、`target` | ML 任務的身分；`task_id` 等於檔名，不支援改名 |
| `output_contract` | `src/` 已定義的輸出契約名稱，含承諾的時程範圍 |
| `schedule.monitoring` | 監控排程 |
| `[health]` | 健康判定的門檻；判定規則由輸出契約定義 |
| `[gate]` | `tolerance`：平台訓練結果的相對容忍幅度，預設 `0.05` |
| `[training]`（選填） | `task_type`、訓練排程、`policies`、`params`、`weather`；只用於平台訓練。沒有這張表的 ML 任務只能靠釘選上線 |

提議：`stale_anchor_max_lag_hours` 留在頂層，不隨其他 `policies` 移進 `[training]`。它是 serving 的規則，只能靠釘選上線的 ML 任務也需要。

`serving/<task_id>.toml`（熱生效）：

| 欄位 | 規則 |
| :--- | :--- |
| `pinned_model` | 選填，64 字元小寫十六進位的 SHA-256；省略表示沒有釘選 |
| `auto_train` | 必填布林；`false` 時 `{task_id}__training_schedule` 以 `SkipReason` 略過，手動執行 `{task_id}__training_job` 不受影響 |

離線測試（`uv run pytest tests/`）檢查：

- 每份 `tasks/*.toml` 通過驗證，`task_id` 等於檔名。
- `tasks/` 與 `serving/` 的 `task_id` 一對一。
- 沒有 `[training]` 的 ML 任務必須有 `pinned_model`，且不得 `auto_train = true`。

API 與 Dagster 啟動時，以工作樹重算 `uv export --frozen --no-dev --no-emit-workspace --package shiro-mlops` 的雜湊，與映像建置時寫入的值不同就啟動失敗；`make smoke-check` 做同樣的檢查。

### 6.8 平台紀錄

五張 append-only 資料表，依 [ADR-0017](../adr/0017-freeze-baseline-ddl-and-record-schema-migrations.md) 以 migration 加入。表名與欄位為提議。

| 資料表 | 一列代表 | 主要欄位 |
| :--- | :--- | :--- |
| `model_handoff`（交付紀錄） | 一次 `submit` | `task_id`、`model_sha256`、`source_revision`、祖先檢查的結果、交付時間 |
| `servability_report` | 一次可服務檢查 | `task_id`、`model_sha256`、出處種類、是否通過、違規清單（JSON）、平台 commit、檢查時間 |
| `gate_verdict` | 一次閘門評估 | `task_id`、候選 SHA、對手 SHA（比 naive 基準時為空）、判定值、雙方與 naive 基準的核心指標、評估窗、雙方被拒的起點、容忍幅度、評估時間 |
| `activation`（生效紀錄） | 現役模型的一次更替 | `task_id`、`model_sha256`、出處種類、依據、依據所引用的紀錄、平台 commit、生效時間 |
| `worktree_update`（工作樹更新紀錄） | 主機更新指令的一次執行 | 更新前後的 commit、做法（只改期望狀態／完整更新）、結果、時間 |

- **依據**有三個值：`gate`（引用一筆 `passed` 的判定）、`rollback`（引用該 SHA 先前的生效紀錄）、`grandfathered`（既有模型接軌，沒有判定）。解除釘選時寫入平台模型的生效紀錄，依據沿用讓它成為平台模型的那一筆。
- **平台模型是哪一份**：取下列三種事件中最近的一筆：平台訓練結果的 `passed` 判定（對手仍是當時的平台模型）、出處種類為 `platform` 的 `rollback` 生效、`grandfathered`。
- **平台 commit** 取自最新一筆 `worktree_update`。已發布預報以發布時刻對照 `worktree_update` 對回平台版本，不另加欄位。

### 6.9 核對與生效

reconciler 是一個 Dagster sensor，每 30–60 秒讀一次 `serving/` 與平台紀錄，決定每個 ML 任務的現役模型應該是哪一份，驗證通過才寫一筆 `activation`。

| 期望 | 生效條件 |
| :--- | :--- |
| `pinned_model` 是交付包，沒有生效過 | 成品在存放區且雜湊相符；有 `passed` 的判定且判定時的對手仍是現役模型；可服務檢查通過 |
| `pinned_model` 在同一個 `task_id` 下生效過（退回） | 成品在存放區且雜湊相符；重新做可服務檢查並通過。不看判定，也不分出處種類 |
| 沒有 `pinned_model` | 平台模型；它成為平台模型時已通過閘門，不再過閘門 |

拒絕時不寫 `activation`，舊的現役模型繼續服務。拒絕理由的代碼（提議）：

| 代碼 | 情形 |
| :--- | :--- |
| `reconcile-model-not-stored` | SHA 不在這個 ML 任務的存放區，包括已被清理的平台模型 |
| `reconcile-sha256-mismatch` | 重新雜湊的結果與目錄名不符 |
| `reconcile-not-servable` | 可服務檢查未通過 |
| `reconcile-no-passing-verdict` | 沒有生效過，也沒有 `passed` 的判定（尚未評估、`failed` 或 `inconclusive`） |
| `reconcile-stale-verdict` | `passed` 的判定當時的對手已不是現役模型 |
| `reconcile-pin-required` | 只能靠釘選上線的 ML 任務沒有 `pinned_model` |

對外介面：

- API 輪詢最新的 `activation`，SHA 與目前載入的不同時先做可服務檢查再原子替換，未通過就保留舊的。API 啟動時對最新的 `activation` 做可服務檢查，未通過就啟動失敗。
- `issued_forecast` 讀同一筆 `activation`，不再直接讀模型目錄。
- `POST /tasks/{task_id}/predict` 的回應帶 `model_sha256`；`/tasks/{task_id}/ready` 帶 `desired_sha` 與 `serving_sha`，期望未生效時仍回 200。
- `make smoke-check` 在期望未生效時判 FAIL，並加上主機端檢查：主要 checkout 在 `main`、沒有未提交的變更、HEAD 等於最新一筆 `worktree_update` 的 commit。

### 6.10 監控

已定案：

- 釘選期間 `{task_id}__monitoring` 照常評估平台模型，報告標明評估對象。
- 平台模型已贏過釘選的交付包時，報告明白顯示。
- 平台訓練連續 3 天沒有勝出判 `WARNING`；期望未生效判 `WARNING`，附 reconciler 的拒絕理由。
- 釘選的是平台出處時，報告標明這一點、訓練截止距今多久，以及待命的平台模型是否已換了一份。
- 健康判定規則由輸出契約定義（[ADR-0019 §2.4](../adr/0019-serve-models-by-declaration-with-platform-owned-inference.md#24-輸出契約是-ml-任務的身分)），取代任務類型的 `assess_health`。

提議（由實作票確認）：

- **現役模型本身的健康**：監控以輸出契約的評分器，在最近的評估窗上重播現役模型（與閘門相同的 `known_by` 規則），套用 `[health]` 判定。動態視界預報另以預報實績（已發布預報帶 `model_sha256`）計算現役模型的核心指標。
- **新舊**：報告一律列出現役模型的訓練截止距今多久，不分出處種類。
- **釘選本身不判 `WARNING`**：釘選是經過審查的決定，也不會到期；`WARNING` 只來自健康判定、連續未勝出與期望未生效。

### 6.11 落地位置

| 草案 | 落地的文件 |
| :--- | :--- |
| §6.1、§6.2，以及 §6.3–§6.6 中 `lab/` 呼叫的介面 | 本文件 §1–§5 改寫 |
| §6.3 成品與宣告、三份清單、§6.4、§6.5 的評分器、§6.7 的任務設定 | [ml-tasks.md](ml-tasks.md) |
| §6.8 的資料表 | [data-contracts.md](data-contracts.md) |
| §6.6 的 sensor、§6.9 的 reconciler、平台模型的清理、訓練與監控排程的變更 | [dagster-schedules.md](dagster-schedules.md) |
| §6.9 的回應欄位與就緒檢查、回應裡固定形狀的 `inputs` 物件 | [rest-api.md](rest-api.md) |
| 主機更新、止損與合回的步驟 | `docs/how-to/` 的部署說明、[github-rulesets.md](github-rulesets.md)、[issue-tracker.md](../agents/issue-tracker.md) |
