# ADR-0018：研究以凍結資料讀取入庫資料，以知悉時間判定 T 時點所知

> - Created: 2026-11-25
> - Last Updated: 2026-11-27
> - Author: Bo-Xue Huang
> - Status: Proposed
> - Related: [ADR-0006](0006-timescaledb-local-storage-layer.md)、[ADR-0008](0008-derive-hourly-actual-load-from-regional-snapshots.md)、[ADR-0012](0012-combine-weather-reference-points-into-weighted-weather.md)、[ADR-0017](0017-freeze-baseline-ddl-and-record-schema-migrations.md)、[GLOSSARY.md](../../GLOSSARY.md)
> - Supersedes: [ADR-0011](0011-co-locate-lab-workspace-with-unidirectional-dependency.md)

---

## 1. Context

M11 要讓**研究者**以 point-in-time 方式唯讀存取已入庫資料，資料要可凍結、可重現，並作為**模型交付包**的評估證據（用語見 [GLOSSARY.md](../../GLOSSARY.md)）。現行做法有三個缺口：

- **point-in-time 參數只篩資料時間**。`at_or_before`、`issued_before`、`as_of` 篩的是負載小時、觀測時間或氣象署發布時間，不篩本系統何時取得資料，所以只有在 T 當下執行時才正確。用過去的 T 回溯，就會多看到資料，例如負載起點晚一小時、T 之後才抓到的預報版本被當成已知（[#273](https://github.com/shiroki9979/shiro-mlops/issues/273)；它的研究檔原放在 `research/` 分支，已遺失，結論見該票）。
- **訓練表快照涵蓋太窄**。[ADR-0011](0011-co-locate-lab-workspace-with-unidirectional-dependency.md) 的快照只有負載與加權觀測天氣。預報版本、逐代表點觀測、區域供需快照與已發布預報都不在裡面，所以回測只能在「氣象已知」的條件下進行。代表點不同的候選必須各凍一份快照，`lab/regional_weights.py` 也只好直接讀線上資料庫。
- **快照的 `as_of` 不是「當時所知」**。快照是在凍結當下查詢「資料時間 ≤ `as_of`」，事後補算的小時也會被納入。可重現性只來自檔案不可覆寫。

各表的 `created_at` 是首次寫入時間，重寫時不會改變，從建表起就存在，是唯一現成可以當作**知悉時間**的欄位。

## 2. Decision

研究一律讀**凍結資料**。凍結資料是與正式 schema 相同的 SQLite 檔，由平台的 repository 與 runner 唯讀讀取。判定「T 時點所知」時，預測輸入以知悉時間篩選，目標取最終值。

### 2.1 point-in-time 語意

- **預測輸入**：負載起點與歷史、預報版本與預報版本回退、降級替代觀測，一律以 `created_at ≤ T` 判定為已知。
- **目標與評估用的實際值**：取凍結時的最終值，不篩知悉時間；事後推算的小時同樣有效。
- **不追回被覆寫的舊值**：負載重算、測站觀測補值與覆寫都以最終值為準，不做雙時間或歷史表遷移。

### 2.2 凍結資料

- **範圍**：可作為 ML 任務目標、輸入或比較對象的資料表，也就是 `raw_taipower_load`、`raw_taipower_regional_supply_demand_snapshot`、`raw_cwa_station_observation`、`raw_cwa_forecast_release`、`raw_cwa_township_forecast`、`issued_forecast`、`issued_forecast_step` 與 `schema_migration`。不帶 `raw_cwa_observation_batch`、台電電力供需快照、機組快照與 `legacy_cwa_weather`。除了區域供需快照之外，`raw_payload` 一律以 NULL 表示，凍結檔的 schema 只在這一點上放寬 NOT NULL。擴充範圍以修改這份清單的 PR 進行。
- **一致切面**：凍結在 PostgreSQL 上開一個 `REPEATABLE READ READ ONLY` 交易，凍結時刻取交易開始時間，只取 `created_at ≤ 凍結時刻` 的列。`created_at` 依 `storage_time` 規則明確寫入，不依賴 SQLite 的預設值。
- **執行者**：凍結程式是 `src/` 內的唯讀 CLI，由研究者隨需執行，不建 Dagster asset 或排程。凍結時刻一律是執行當下，不接受參數。
- **識別與不可覆寫**：存放於 `data/lab/freezes/<凍結時刻>.sqlite`（不進版控），旁附清單，內容為凍結時刻、git revision、schema 遷移版本、各表列數、檔案 SHA-256，以及被排除的表與欄位。目標已存在時拋 `FileExistsError`；先寫暫存檔，再以 hard link 放到定位。
- **保留**：被研究報告或模型交付包以 SHA-256 引用的凍結資料不得刪除，其餘由研究者手動清理，平台不自動清理。凍結資料怎麼隨交付包搬到平台，不在本 ADR 決定。

### 2.3 讀取與一致性

- **唯一入口**：`src/` 提供 `open_freeze(path)`，以 `mode=ro` 開啟凍結檔並依清單驗證 SHA-256，回傳的 `TaskRuntime` 包著同一個 `TimeSeriesRepository`。`lab/` 不得以其他方式建構 repository 或讀取資料庫連線設定，也不連線正式資料庫。
- **知悉時間在 repository 層篩選**：runner 用到的預測輸入查詢（`fetch_latest_load`、`fetch_load_range`、`fetch_cwa_forecast_rows`、`fetch_cwa_station_observations`）加上必填參數 `known_by`，篩選 `created_at ≤ known_by`。`check_task_ready`、`predict_task`、`resolve_weather` 一律傳 `known_by=as_of`；`load_training_data` 不篩。serving 與回測走同一段程式。
- **標準回測**：每個起點是模擬的發布時刻 T，對齊已發布預報的排程整點。負載起點取 `known_by=T` 下最新已知的小時，天氣照 serving 規則以預報版本、預報版本回退與降級解析，提前時數從 T 起算。報告記錄每個起點的預報運行狀態。以觀測天氣回測的「氣象已知」模式保留為選用的診斷，報告須標明模式；交付包的評估證據只認標準模式。
- **取代訓練表快照**：研究以 `open_freeze` 取得 `TaskRuntime` 後，直接呼叫 `load_training_data(as_of=…)`。`write_snapshot`、`read_snapshot`、`snapshot_path`、`variant` 與 CLI 一併移除。報告的重現紀錄改記凍結資料的 SHA-256 與訓練截止 `as_of`。

### Rationale & Alternatives Considered

- **取捨一：知悉時間的來源**
  - **選定方案：`created_at`**。所有表都有，從建表起就存在；對只新增的表就是精確的知悉時間。一次性補算的負載小時在當時的起點上也算未知，這與當時 serving 的實際處境一致。
  - **候選方案 A：資料時間加上排程延遲規則**（例如負載小時 H 視為 H+1h05m 才已知）。不需新欄位，但那是排程模型而不是事實：擷取中斷、重試、手動執行與補算都會讓規則失真，而且規則要隨排程同步維護。未採納。
  - **候選方案 B：把會覆寫的表改為雙時間或另存歷史表**。可以精確回答「T 時表內存的是什麼值」，但要做 schema 遷移，改動前已被覆寫的舊值也找不回來。目標與實際值本來就該用最終值，預測輸入的覆寫幅度又小（ADR-0008 記錄全量重算最大差 7e-12 MW）。未採納。
  - **候選方案 C：由原始保存物重算**。符合「推算而非回補」，但推算門檻沒有逐列記錄，同 slot 重寫的快照也已遺失，重算成本還會隨歷史增長。未採納，因此凍結資料不帶大型原始回應。
- **取捨二：凍結的載體**
  - **選定方案：同 schema 的 SQLite 檔，經平台 repository 唯讀讀取**。預報版本回退、降級、預測輸入關卡與訓練資料組裝都不用改就能讀凍結資料，研究和 serving 共用同一套查詢，不會出現研究版的查詢規則。測試本來就以 SQLite 跑同一份 DDL 與遷移（ADR-0017）。
  - **候選方案 D：每張表一個 parquet**。體積小、pandas 好用，但要另寫一份讀 parquet 的 repository，查詢規則就有了第二份實作，正是 ADR-0011 想避免的研究與正式行為分叉。未採納。
  - **候選方案 E：`pg_dump` 還原成唯讀 TimescaleDB 容器**。方言最忠實，但每次研究都要起容器，凍結與讀取的成本都高，與「需要新資料就重新凍結」的使用方式衝突。未採納。
- **取捨三：凍結的範圍**
  - **選定方案：同一凍結時刻，取可作為 ML 目標、輸入或比較對象的全部資料表**。切面一致，研究者不必事先猜要用哪些資料。
  - **候選方案 F：依 ML 任務凍結訓練表**（ADR-0011 現行作法）。缺預報版本與逐代表點觀測，代表點一換就要另凍一份。未採納。
  - **候選方案 G：由研究者逐資料集挑選**。不同資料集若在不同時刻凍結，切面就不一致。未採納。
- **取捨四：研究能否直連正式資料庫**
  - **選定方案：不開放，研究一律讀凍結資料**。評估證據都能指回一份以 SHA-256 識別的凍結資料，這條邊界由 `open_freeze` 與慣例檢查強制，不靠默契。
  - **候選方案 H：探索可以直連，只有證據要凍結**。界線只能靠研究者自律維持，不符合「契約按兩個人設計」的前提。未採納。

## 3. Consequences

- **正面效益（Positive）**：
  - 回測可以使用預報天氣與降級，結果不再只是「氣象已知」的條件式數字，也能和已發布預報直接比較。
  - 代表點與權重成為讀取時的研究變數，不必再為每個候選另凍一份快照。
  - serving 與回測共用知悉時間的篩選程式，`known_by` 是必填參數，漏傳會在型別檢查階段被抓到。
- **代價與風險（Trade-offs & Risks）**：
  - 凍結檔比訓練表快照大得多，而且隨歷史增長。原始回應已經排除，但實際體積在正式資料上還沒量測。
  - 讀取 SQL 必須持續在 TimescaleDB 與 SQLite 兩種方言下都成立；凍結檔的 schema 在 `raw_payload` 的 NOT NULL 上與正式資料庫不同。
  - 標準回測可用的起點，限於氣象署預報開始入庫之後的時段，比現行「氣象已知」模式少。
  - `created_at` 是交易開始時間而不是 commit 時間；同一批寫入的知悉時間在秒級內可能略早於實際可見的時刻。
  - 兩份既有研究報告使用舊的訓練表快照，無法以新機制逐位元重現，只能保留為歷史紀錄。
- **不做／延後範圍（Out of Scope / Deferred）**：
  - 研究者是否以預報天氣訓練（地圖「訓練與 serving 的特徵一致性」）。
  - 凍結資料隨模型交付包搬運、平台端的副本與驗收方式（[#277](https://github.com/shiroki9979/shiro-mlops/issues/277) 與地圖「交付包的搬運與存放」）。
  - 研究者自帶外部資料與新資料來源的擷取。
  - 已發布預報保存當時的輸入。

## 4. Compliance

- 單元測試（往返等價）：以 SQLite fixture 模擬正式資料庫，凍結後以 `open_freeze` 開啟。對同一組 `(as_of, known_by)`，`load_training_data`、`check_task_ready`、`predict_task` 讀凍結資料與讀原庫的結果相等。
- 單元測試（知悉時間）：`created_at` 晚於 T 的列，包括晚到的預報版本、晚補的行政區列與一次性補算的負載小時，不得出現在 `known_by=T` 的預測輸入中。
- 單元測試（凍結檔）：`open_freeze` 回傳的 runtime 寫入時失敗；SHA-256 與清單不符時拋錯；對已存在的凍結時刻再次凍結時拋 `FileExistsError`，原檔不變。
- 慣例檢查：`lab/` 除了經由 `open_freeze` 之外，不得建構 `TimeSeriesRepository` 或讀取資料庫連線設定。
- `ops-acceptance`：在正式 TimescaleDB 上實測一次凍結，確認 `REPEATABLE READ` 切面的一致性、凍結耗時與凍結檔體積。

## 5. Notes

- 決策經 2026-11-25 的設計討論定案（[GitHub #276](https://github.com/shiroki9979/shiro-mlops/issues/276)，地圖 [#270](https://github.com/shiroki9979/shiro-mlops/issues/270)），事實來源為 [#273](https://github.com/shiroki9979/shiro-mlops/issues/273) 的盤點。狀態維持 `Proposed`，待 M11 規格定稿時改為 `Accepted`。
- 部分取代 [ADR-0011](0011-co-locate-lab-workspace-with-unidirectional-dependency.md)：「訓練表層級的不可變快照」與候選方案 B、C 的取捨由本 ADR 取代；`lab` → `shiro_mlops` 的單向相依、`uv` workspace 與搜尋／評估起點分離照舊有效。
