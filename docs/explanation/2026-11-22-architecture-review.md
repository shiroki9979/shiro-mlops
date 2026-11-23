<!-- markdownlint-disable MD024 -->
# 架構檢視：module 加深候選紀錄（2026-11-22）

- 建立日期：2026-11-22
- 最後更新：2026-11-23
- 文件類型：Explanation（架構現況與取捨分析）
- 狀態：候選 2 已由 [#160](https://github.com/shiroki9979/shiro-mlops/issues/160) 實作（2026-11-22）；候選 3 已由 [#228](https://github.com/shiroki9979/shiro-mlops/issues/228) 實作（2026-11-22）；候選 5 已由 [#230](https://github.com/shiroki9979/shiro-mlops/issues/230) 實作（2026-11-22）；候選 6 已由 [#231](https://github.com/shiroki9979/shiro-mlops/issues/231) 實作（2026-11-22）；候選 8 已由 [#233](https://github.com/shiroki9979/shiro-mlops/issues/233) 實作（2026-11-23）；其餘 3 個候選待評估，各自登記為技術債或併入既有 issue（見下表）；候選 1 揭露的預報錯誤另登記為 bug [#226](https://github.com/shiroki9979/shiro-mlops/issues/226)
- 檢視基準：`45f4b8e9d004e5e316c96d79086b71a9dd0dbebd`
- 前次檢視：[2026-09-27 架構檢視](2026-09-27-architecture-review.md)

## 範圍與結論

本次沿 2026-09-01 以來的非 merge commits 追查變更熱點：
`repository.py`、`assets.py`、`api.py`、`runner.py` 分別出現在 36、29、19、17 個 commits，`service/data_explorer/` 合計 30 個。
檢視分兩路：資料擷取、儲存與編排；ML 任務、serving 與預報發布。
前次已處理或暫緩的項目（[#102](https://github.com/shiroki9979/shiro-mlops/issues/102)、[#103](https://github.com/shiroki9979/shiro-mlops/issues/103)、[#104](https://github.com/shiroki9979/shiro-mlops/issues/104)）不重複列入。

| 候選 | 建議強度 | 主要收益 | 建議時機 |
| :--- | :--- | :--- | :--- |
| 1. 收斂預測輸入關卡 | Strong | serving 與滾動起點回測拒絕同一批起點 | 修正 [#226](https://github.com/shiroki9979/shiro-mlops/issues/226) 時（[#227](https://github.com/shiroki9979/shiro-mlops/issues/227)） |
| 2. 集中儲存時刻轉換 | Strong | 單一儲存形式，跨表 SQL join 可用 | 併入 [#160](https://github.com/shiroki9979/shiro-mlops/issues/160)；已實作（2026-11-22，子 issue [#237](https://github.com/shiroki9979/shiro-mlops/issues/237)–[#242](https://github.com/shiroki9979/shiro-mlops/issues/242)） |
| 3. 由單一 module 擁有全台逐時實際負載的存取 | Strong | ADR-0008 的口徑規則只在一處成立 | 下次修改全台逐時實際負載的推算或讀取時（[#228](https://github.com/shiroki9979/shiro-mlops/issues/228)）；已實作（2026-11-22，子 issue [#298](https://github.com/shiroki9979/shiro-mlops/issues/298)、[#300](https://github.com/shiroki9979/shiro-mlops/issues/300)–[#303](https://github.com/shiroki9979/shiro-mlops/issues/303)） |
| 4. 以資料集定義推導營運資料檢視器的查詢 | Strong | series 端點一次實作，8 個資料集共用 | M9 series 端點開工前（[#229](https://github.com/shiroki9979/shiro-mlops/issues/229)） |
| 5. 集中已部署任務的模型狀態與預測 | Worth exploring | API 測試不再 patch module 全域 | 下次修改 API 的模型載入或就緒判定時（[#230](https://github.com/shiroki9979/shiro-mlops/issues/230)）；已實作（2026-11-22） |
| 6. 擷取來源 fetch 改為注入的 adapter | Worth exploring | 擷取 asset 測試不再 patch module 路徑 | 下次新增擷取來源或修改 asset 的 fetch 時（[#231](https://github.com/shiroki9979/shiro-mlops/issues/231)）；已實作（2026-11-22） |
| 7. 已發布預報擁有預報步與提前時數 | Worth exploring | 提前時數只有一份定義 | 下次修改提前時數或已發布預報的欄位契約時（[#232](https://github.com/shiroki9979/shiro-mlops/issues/232)） |
| 8. TimeSeriesRepository 收斂為 composition root | Worth exploring | 刪除 12 個 pass-through 方法 | 候選 2、3 完成後（[#233](https://github.com/shiroki9979/shiro-mlops/issues/233)）；已實作（2026-11-23，子 issue [#311](https://github.com/shiroki9979/shiro-mlops/issues/311)–[#316](https://github.com/shiroki9979/shiro-mlops/issues/316)） |

優先建議候選 1：它是唯一正在產出錯誤結果的候選，依賴類別為 in-process，成本最低。
次選候選 4：M9 的 series 端點會為 8 個資料集再寫一次資料集知識，應在開工前完成。

## 評估用語

沿用[前次檢視的評估用語](2026-09-27-architecture-review.md#評估用語)。
另以依賴類別標示候選如何跨 seam 測試：in-process（純計算，直接測）、local-substitutable（有本機替身，如 SQLite）、mock（真正的外部依賴，以注入的 port 隔離）。

## 候選 1：收斂預測輸入關卡

### 現況與證據

[ml-tasks.md](../reference/ml-tasks.md) §2 規定 `PredictionData` 交付時負載起點新鮮、天氣完整，任務類型不得以常數補值；lookback 內的負載是否完整則沒有保證。
[runner.py](../../src/shiro_mlops/tasks/runner.py) 的 `_prepare_prediction` 只確保負載起點未過舊；
`_require_history_coverage` 只在任務類型宣告 `history_coverage` 時檢查，目前只有高負載預警宣告。

動態視界預報的 `RecursiveRegression.requirements`（[recursive_regression.py](../../src/shiro_mlops/tasks/types/recursive_regression.py):93-96）沒有宣告，lags 為 `[1, 2, 24, 48, 168]`。
負載起點前 168 小時內缺任一個有效逐時觀測時，[transformers.py](../../src/shiro_mlops/features/transformers.py) 的 `create_lag_features` 依時間 reindex 得到 NaN，`_predict_step` 未檢查即交給 LightGBM。
訓練時特徵管線以 `dropna` 或暖機補值處理缺值，booster 沒有見過 NaN；此時 LightGBM 把 NaN 視同 0，等於以 0 MW 作為 lag 遞迴推演。
產出的預報仍標為正常預報並存成已發布預報，違反 GLOSSARY「全台逐時實際負載沒有替代來源」。此錯誤登記為 [#226](https://github.com/shiroki9979/shiro-mlops/issues/226)。

[lab/backtest.py](../../lab/backtest.py) 遇到同一情況會拒絕該起點（`_check_origin`、`_slice_and_validate_origin_history`），並自行建構 `PredictionData`；
滾動起點回測與 serving 實際處理的起點集合因此不同。
回測中「關閉驗證期」的 `validation_start = origin + 1h` 寫了兩次，輸出欄名 `predicted_load_mw` 由 3 個 module 各自知道。

### 加深方向與取捨

```text
Before：runner〔起點過舊〕＋任務類型自行宣告〔coverage〕‖ lab〔自寫起點、lookback、天氣檢查〕
After ：runner 的 frame／回測快照 frame → 預測輸入關卡〔起點過舊／lookback 與 lag 完整／天氣涵蓋每個目標小時〕→ PredictionData 或具型別的拒絕
```

- **depth 與 deletion test**：`_require_history_coverage` 只服務一種任務類型，範圍過窄；刪除 lab 的起點檢查後，規則不會在 src 出現，表示這條規則沒有歸屬。由關卡吸收這些規則可增加 depth。
- **locality／leverage**：起點有效性只有一份定義，serving、已發布預報與滾動起點回測共用。
- **seam／adapter**：關卡本身為 in-process；runner 以 repository 讀出的 frame 餵入、lab 以快照 frame 餵入，兩個 adapter 使 seam 成立。
- **成本與限制**：lag 完整性改由 requirements 推導後，負載缺口會讓 `/predict` 回 503、已發布預報留下缺口；這是 GLOSSARY 定義的直接推論，須同步更新 [lab.md](../reference/lab.md) §2 的起點有效性。可再把 `TaskRuntime` 依賴的 repository 收窄到 runner 實際使用的讀取方法。

### 測試保留重點

先以紅燈測試記錄「lag 小時缺失時拒絕」，再補「負載起點過舊時拒絕」與「天氣缺一個目標小時時拒絕」，三者都直接餵 frame。
[test_task_runner.py](../../tests/integration/test_task_runner.py) 中以 monkeypatch 記錄 `fetch_load_range` 視窗的測試可改為關卡測試；
lab 起點檢查的規則層測試移到 src，lab 只保留回測彙整的測試。

## 候選 2：集中儲存時刻轉換

> **狀態（2026-11-22）**：已由 [#160](https://github.com/shiroki9979/shiro-mlops/issues/160)（子 issue [#237](https://github.com/shiroki9979/shiro-mlops/issues/237)–[#242](https://github.com/shiroki9979/shiro-mlops/issues/242)）實作。
> 本節指向的程式位置（`_taiwan_instant_to_utc`、`taiwan_instant_to_utc`、`timefmt.to_sql_utc`、`sqlite_time_key`、`SQLITE_NAIVE_UTC_TABLES`、`TODO(#160)` 等）記錄檢視基準當時的狀態，僅供歷史參考；現行契約見 [data-contracts.md](../reference/data-contracts.md)。

### 現況與證據

[data-contracts.md](../reference/data-contracts.md) 規定寫入 `TIMESTAMPTZ` 前由 repository 一律轉為 UTC，但這是每個 store 各自的義務，轉換 helper 有兩份：
[repository.py](../../src/shiro_mlops/data/repository.py) 的 `_taiwan_instant_to_utc` docstring 寫 naive，實際回傳 aware UTC；
[repository_utils.py](../../src/shiro_mlops/data/repository_utils.py) 的 `taiwan_instant_to_utc` 回傳 naive UTC。
結果負載表與 CWA 兩張表存 aware，台電三張快照表與已發布預報表存 naive；營運資料檢視器的 `timefmt.to_sql_utc` 另產生 aware。
兩份 `serialize_raw_payload` 的語意也不同：一份把字串再做 JSON 編碼，一份讓字串直接通過。

格式分歧擴散出的補償：
[pagination.py](../../src/shiro_mlops/service/data_explorer/pagination.py) 的 `sqlite_time_key` 在 SQL 內正規化兩種字串；
預報實績改在 Python 端配對（`repository.py` 的 `TODO(#160)`）；
[test_data_explorer_exact_window.py](../../tests/unit/test_data_explorer_exact_window.py) 以 `SQLITE_NAIVE_UTC_TABLES` 依表切換格式。
另有未驗證的風險：naive 參數寫入 `timestamptz` 時依 session TimeZone 解讀，目前的正確性依賴伺服器預設為 UTC。

### 加深方向與取捨

```text
Before：各 store 自選 helper〔aware 或 naive〕→ 補償散在 pagination、預報實績、測試 fixture
After ：所有 store 與營運資料檢視器 → 儲存時刻 module〔台灣本地 → 單一儲存形式／儲存值 → 台灣本地 naive／半開窗 → SQL 條件與參數〕
```

- **depth 與 deletion test**：兩個同名 helper 互為重複，刪掉一個不會失去行為；`repository_utils` 是一組 shallow 的單行函式，但「儲存時刻」這個概念在 4 個 store 與營運資料檢視器反覆出現，值得一個 deep 的歸屬。
- **locality／leverage**：新 store 不必自選 helper；跨表 SQL join 恢復可用。
- **seam／adapter**：local-substitutable；SQLite 與 TimescaleDB 都經同一 module 轉換，不新增 port。
- **成本與限制**：正式 `timestamptz` 不需資料遷移，SQLite 測試資料需重建。與候選 3 的半開窗重疊，建議先做或同做。台電快照 store 的讀回政策分歧（區域快照遇 NULL 時刻會 raise，另外兩個以查詢條件代填）可隨此一起收斂。

### 測試保留重點

以已知範例測儲存時刻 module：台北 14:00 對應 06:00Z、aware 輸入保留原瞬間、半開窗含左不含右。
新增 SQLite 跨表 join 測試（現況會失敗）；可另加 opt-in 驗收，在非 UTC session 下經各 store 寫入再讀回。
以 raw SQL 斷言儲存格式的 store 測試與 `SQLITE_NAIVE_UTC_TABLES` 分流可移除。

## 候選 3：由單一 module 擁有全台逐時實際負載的存取

> **狀態（2026-11-22）**：已由 [#228](https://github.com/shiroki9979/shiro-mlops/issues/228)（子 issue [#298](https://github.com/shiroki9979/shiro-mlops/issues/298)、[#300](https://github.com/shiroki9979/shiro-mlops/issues/300)–[#303](https://github.com/shiroki9979/shiro-mlops/issues/303)）實作。[hourly_actual_load_store.py](../../src/shiro_mlops/data/hourly_actual_load_store.py) 的 `HourlyActualLoadStore` 擁有 `raw_taipower_load` 與推算來源常數：寫入內建推算來源，以台灣本地半開窗讀推算序列，並提供最新推算小時、累積盤點、依排程推算，以及以 `ON CONFLICT DO NOTHING` 寫入、不覆寫任何既有列的區間補推；`TimeSeriesRepository` 的負載方法已刪除，asset、補推腳本與 runner 只呼叫 store。
> 與本節方向的差異：營運資料檢視器已由候選 4 改為宣告式資料集定義，維持原樣，只改由 store 匯入口徑常數；預報實績 join 跨已發布預報與負載兩張表，留在 repository，以同一常數綁參數。runner 要含終點的序列，由 runner 在一處把終點換成下一小時再交給 store 的半開窗；`with_datetime_column` 仍供天氣與 Feast 匯出使用。
> 本節指向的程式位置（`fetch_load_range`、`_valid_hourly_load`、`hourly_load.py`、`catalog.py`、`completeness.py`、各自切出的窄 Protocol 等）記錄檢視基準當時的狀態，僅供歷史參考；現行契約見 [data-contracts.md](../reference/data-contracts.md) §3 與 [ml-tasks.md](../reference/ml-tasks.md)。
> **狀態（2026-11-23）**：「預報實績 join 留在 repository」一句記錄 #228 完成當時的狀態；[#313](https://github.com/shiroki9979/shiro-mlops/issues/313) 已把這個 join 移入 [forecast_track_record.py](../../src/shiro_mlops/data/forecast_track_record.py) 的 `ForecastTrackRecordStore`，`TimeSeriesRepository` 只交出這個 store。

### 現況與證據

ADR-0008 規定訓練、serving 與 drift 只讀 `source='regional_snapshot_sum'`，這條規則靠呼叫端自己記得傳：
[runner.py](../../src/shiro_mlops/tasks/runner.py) 兩處與預報實績配對各傳一次 `source`，營運資料檢視器的 `hourly_load.py`、`catalog.py`、`completeness.py` 各自手寫 SQL 與口徑篩選；
`fetch_load_range` 不傳 `source` 時會混入舊口徑。

`fetch_load_range` 是閉區間，呼叫端用的卻都是半開窗，`_valid_hourly_load` 須手動排除恰在窗終點的那一小時。
儲存欄名 `time` 洩漏到呼叫端：runner 與 Feast 匯出以 `with_datetime_column` 改名，`assets.py` 與 rederive 腳本直接取 `time` 欄。
呼叫端從 repository 的 22 個方法中各自切出窄 Protocol（`tasks/accumulation.py`、`scripts/rederive_hourly_actual_load.py`）。

「這次排程要推算哪些小時」的組合寫在 [assets.py](../../src/shiro_mlops/pipelines/assets.py) 的 `raw_taipower_load` 本體（查最新推算小時 → `catch_up_window` → `uncovered_gap` → 讀快照 → 推算 → upsert），只能經 Dagster job 測試。
[#113](https://github.com/shiroki9979/shiro-mlops/issues/113) 的錯誤出在這段組合，不在已抽出的純函式；其修正 `85aa44c` 動了 11 個檔案。

### 加深方向與取捨

```text
Before：runner／accumulation／asset／rederive／預報實績 → 22 個方法的 repository（各自傳 source、改欄名）；營運資料檢視器手寫 SQL 直接讀表
After ：上述呼叫端 → 全台逐時實際負載 module〔口徑內建／半開小時窗／依排程推算／區間補推不覆寫／最新推算小時／累積盤點〕→ raw_taipower_load
```

- **depth 與 deletion test**：`_latest_derived_hour` 是 pass-through；`with_datetime_column` 只因欄名洩漏而存在。[hourly_actual_load.py](../../src/shiro_mlops/data/hourly_actual_load.py) 的純函式是 deep 的，原樣保留；缺的是組合的歸屬。
- **locality／leverage**：ADR-0008 的口徑規則與半開窗只在一處成立；舊口徑只經累積盤點的 `legacy_rows` 與補推的「該小時是否已有任何列」檢查出現。
- **seam／adapter**：local-substitutable；SQLite 替身由 `ensure_timescale_hypertables` 建立，TimescaleDB 驗收維持 opt-in。
- **成本與限制**：`lab/tests` 以 `upsert_taipower_load` 建 fixture，需同 PR 調整；營運資料檢視器的讀取改由候選 4 的資料集定義引用同一口徑規則。

### 測試保留重點

以 SQLite 直接測 module 的 interface：停機恢復後補上邊界小時、舊口徑列不出現在序列、視窗為半開、補推不覆寫既有列。
[test_hourly_actual_load_job.py](../../tests/integration/test_hourly_actual_load_job.py) 縮為一兩個「排程 → config」接線測試；
[test_hourly_actual_load.py](../../tests/unit/test_hourly_actual_load.py) 的純函式測試保留。

## 候選 4：以資料集定義推導營運資料檢視器的查詢

### 現況與證據

一個資料集的知識（表、時間欄、排序鍵、篩選、完整度）散在 4 到 6 個 module。
以逐時用電負載為例：[specs.py](https://github.com/shiroki9979/shiro-mlops/blob/45f4b8e9d004e5e316c96d79086b71a9dd0dbebd/src/shiro_mlops/service/data_explorer/specs.py) 宣告排序，`hourly_load.py`、`catalog.py`、`completeness.py` 各自寫表名與口徑篩選（其中兩段 where 組裝逐行相同），`pagination.py` 的 `CURSOR_TIME_COLS` 另記時間欄。
`DATASET_SPECS` 是被動的 dict，不擁有任何行為。

[query.py](../../src/shiro_mlops/service/data_explorer/query.py) 以 14 個鍵的白名單決定哪些篩選寫入 cursor；新增篩選若沒有同步加進白名單，篩選會被靜默丟棄。
[M9](../ROADMAP.md)（[#212](https://github.com/shiroki9979/shiro-mlops/issues/212)）要為 8 個資料集加 series 端點、狀態 sparkline 與整窗完整度；照現行結構，每個資料集的知識要再寫一次。

### 加深方向與取捨

```text
Before：specs〔排序〕↔ reader〔表／篩選／時間欄〕↔ catalog〔表／口徑〕↔ completeness〔表／where〕↔ query〔篩選白名單〕↔ pagination〔時間欄〕
After ：資料集定義 ×8 → 資料集查詢 module〔keyset 分頁／cursor 綁定篩選／新鮮度與完整度／series 聚合〕→ list、status、series
```

- **depth 與 deletion test**：`DatasetReader` 刪除後分頁流程會散回 8 個 reader，值得保留；completeness 的函式各只有一兩個呼叫端且各自重推 SQL。「資料集」這個概念目前沒有 deep 的歸屬。
- **locality／leverage**：新增資料集或篩選只寫一份定義；series 一次實作，8 個資料集共用。
- **seam／adapter**：local-substitutable；SQLite fixture 與 TimescaleDB 整合測試皆已存在。
- **成本與限制**：既有的 `DatasetReader` 分頁與 [cursor.py](../../src/shiro_mlops/service/data_explorer/cursor.py) 移入 module 內部而非重寫；[data-explorer.md](../reference/data-explorer.md) §7 須同 PR 更新。

### 測試保留重點

改以「資料集 × list／status／series」的 interface 測試為主，用 SQLite fixture，`tests/scenarios/data_explorer_*.py` 可作基礎。
綁定內部的測試（`test_data_explorer_exact_window.py`、completeness helper 測試、斷言白名單內容的測試）可移除；`cursor.py` 的測試保留。

## 候選 5：集中已部署任務的模型狀態與預測

> **狀態（2026-11-22）**：已由 [#230](https://github.com/shiroki9979/shiro-mlops/issues/230) 實作。[served_tasks.py](../../src/shiro_mlops/service/served_tasks.py) 的 `ServedTasks` 擁有模型狀態（含 sha256）、就緒判定、預測與錯誤分類，API 以 `create_app` 注入；`/health` 逐任務回報 `model_sha256` 與 `reason`，repository 只在啟動時建立一次。
> 本節記錄檢視基準當時的狀態；對照 dev `4e2a7d4` 有三處校正：完整的「查 key 再問原因」只在 `_readiness`、`_predict`，`health_check` 只查 key；monkeypatch 為 33 處（含 `tests/scenarios/` 2 處）；#204 改到 `api.py` 的是 `c725139`、`7062546` 兩次。

### 現況與證據

[api.py](../../src/shiro_mlops/service/api.py) 的記憶體 `ModelStore` 直接公開 `models` 與 `load_errors` 兩個 dict；
「查 key，不在就問 `missing_model_reason`」在 `_readiness`、`_predict`、`health_check` 各寫一次。
runner 的 `model=None` 分支在正式路徑走不到（API 先檢查過）；api 捕捉的 `TaskNotReady` 只由訓練與監控路徑拋出，`predict_task` 不會拋出。

測試只能 monkeypatch module 全域：`model_store`、`repository_store`、`request_clock` 共被 patch 31 次；
[test_api.py](../../tests/integration/test_api.py) 甚至穿過兩個 module patch `shiro_mlops.tasks.runner.resolve_weather`。
營運資料檢視器的 [router.py](../../src/shiro_mlops/service/data_explorer/router.py) 在函式內 import api 取得 `repository_store`。
API 以 `load_model` 載入，丟掉了 `load_model_with_sha256` 提供的 sha256，無法回報正在 serve 的模型版本。
[#204](https://github.com/shiroki9979/shiro-mlops/issues/204) 在這個 seam 上連改三次（`c725139`、`9e2bb45`、`7062546`）。

### 加深方向與取捨

```text
Before：api.py module 全域〔model_store／repository_store／request_clock〕＋三處 lookup ＋ runner 走不到的分支；router 反向 import api
After ：api.py〔HTTP 對映〕→ 已部署任務 module〔模型狀態含 sha／就緒／預測／錯誤分類〕→ runner、model_store、repository、clock
```

- **depth 與 deletion test**：記憶體 `ModelStore` 是 shallow 的，interface 就是公開的 dict；刪除它邏輯會回到三個呼叫端，所以值得存在，但沒有藏住複雜度。runner 的 `model=None` 分支是 pass-through，可刪。
- **locality／leverage**：模型狀態、就緒判定與錯誤分類（unavailable 或 internal）集中一處；HTTP 狀態碼對映只留在 api.py。
- **seam／adapter**：local-substitutable（暫存 model root、SQLite、固定 clock）；FastAPI 經 app state 或 dependency 取得 module，API 測試以 fake 替換。
- **成本與限制**：[model_store.py](../../src/shiro_mlops/tasks/model_store.py)（檔案系統、原子交換、per-task 鎖）已夠 deep，不動。已發布預報管線每個 tick 重新載入模型，生命週期不同，只共用「含 sha 的模型」型別。

### 測試保留重點

以暫存 model root、SQLite 與固定 clock 測 module 的各種回應：未訓練、載入失敗、負載起點過舊、正常預報、降級預報。
API 測試只驗 HTTP 對映（200／503／500 的形狀），module 全域的 monkeypatch 大多可移除。

## 候選 6：擷取來源 fetch 改為注入的 adapter

> **狀態（2026-11-22）**：已由 [#231](https://github.com/shiroki9979/shiro-mlops/issues/231) 實作。台電 port 回傳原始 payload、由 asset parse；CWA port 維持 `CWAClient` 的 typed 層級，因既有測試以 typed batch 建構資料。

### 現況與證據

repository 已是 Dagster resource，來源 client 卻在 [assets.py](../../src/shiro_mlops/pipelines/assets.py) 的 asset 本體內以 settings 直接建立。
測試因此只能 patch module 路徑：台電三個來源的 `httpx.Client` 約 20 處、`pipelines.assets.CWAClient` 6 處，另有 3 處以 `monkeypatch.setattr(CWAClient, ...)` 替換方法。
`pipelines.assets.resolve_snapshot_observed_at` 被 patch 15 次，繞過了 asset 已提供的 `observed_at` config。
slot 取整規則出現在三處：schedule 的 `_taiwan_tick_iso`、asset 的 `resolve_snapshot_observed_at`、client 的 `fetch_snapshot`。
台電三個 asset 測試檔各自複製一份 `_mock_httpx_response`。

### 加深方向與取捨

```text
Before：asset 本體〔settings → httpx.Client／CWAClient〕；測試 patch module 路徑；slot 取整 ×3
After ：schedule／config〔唯一決定 slot〕→ asset〔取 payload → parse → upsert〕→ 來源 fetch port ← HTTP adapter（正式）／fixture adapter（測試）
```

- **depth 與 deletion test**：client 的 `fetch_snapshot(s)` 只是「取整 slot 再 parse(fetch_payload())」的 pass-through；parse 函式是 deep 的，留在各來源 module。
- **locality／leverage**：slot 規則只剩一處；三個台電 asset 測試可合併為參數化測試。
- **seam／adapter**：mock；CWA 與台電是真正的外部依賴，HTTP adapter 與 fixture adapter 兩個實作使 seam 成立。
- **成本與限制**：與 [ADR-0007](../adr/0007-isolate-cwa-access-behind-scheduled-ingestion.md)（CWA 只經排程入庫）一致；`_get_time_series_repo` 的 fallback 在 `required_resource_keys` 下走不到，且會掩蓋設定錯誤，可一併移除。

### 測試保留重點

以 fixture adapter 驅動 asset、以 config 指定 slot，取代所有 module 路徑的 patch；HTTP adapter 單獨測一次。

## 候選 7：已發布預報擁有預報步與提前時數

### 現況與證據

GLOSSARY 對提前時數有兩條規則：目標小時不晚於發布時刻不算預報；不足一小時以一小時計。這兩條規則分別實作在三個 module：
[issued_forecast_repository.py](../../src/shiro_mlops/data/issued_forecast_repository.py) 的 SQL（`target_hour > issued_at`）、
[forecast_view.py](../../src/shiro_mlops/data/forecast_view.py) 的 inline 預報步篩選、
[forecast_track_record.py](../../src/shiro_mlops/data/forecast_track_record.py) 的 `TrackRecordPair.lead_time_hours`（`math.ceil`）。

[pipelines/issued_forecast.py](../../src/shiro_mlops/pipelines/issued_forecast.py) 走通用的 `predict_task`，卻從 `recursive_regression` import `PREDICTION_COL`。
預報實績同時以 dataclass 與 JSON 讀回的 dict 兩種形狀存在，`forecast_view._with_offset` 因此須同時接受 `datetime` 與 `str`。

### 加深方向與取捨

```text
Before：pipeline〔寫死任務類型欄名〕→ IssuedForecast〔只是資料〕；repository SQL／forecast_view／TrackRecordPair 各自實作提前時數規則
After ：pipeline → 已發布預報 module〔由預測建立／預報步篩選／每步提前時數〕→ repository（SQL 下推）、forecast_view、預報實績
```

- **depth 與 deletion test**：`latest_issued_forecast_document` 裡的篩選是重複的規則；`IssuedForecast` 只是帶驗證的資料，不擁有任何規則。
- **locality／leverage**：負載起點與發布時刻的關係若改變，只改一處。
- **seam／adapter**：in-process；repository 的 SQL 只是下推最佳化，以同一組 interface 測試驗證。
- **成本與限制**：與 [ADR-0013](../adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md)、[ADR-0015](../adr/0015-publish-forecast-view-as-static-precomputed-output.md) 一致；預報實績 module 一併擁有自己 artifact 的序列化與空狀態。

### 測試保留重點

新增已發布預報 module 的 interface 測試，涵蓋負載起點落後於發布時刻的情境；
[test_forecast_view_documents.py](../../tests/unit/test_forecast_view_documents.py) 的 fixture 契約測試保留。

## 候選 8：TimeSeriesRepository 收斂為 composition root

> **狀態（2026-11-23）**：已由 [#233](https://github.com/shiroki9979/shiro-mlops/issues/233)（子 issue [#311](https://github.com/shiroki9979/shiro-mlops/issues/311)–[#316](https://github.com/shiroki9979/shiro-mlops/issues/316)）實作。[repository.py](../../src/shiro_mlops/data/repository.py) 的 `TimeSeriesRepository` 沒有讀寫方法，只建立一個 engine、做一次可關閉的 schema init，並交出各概念 store：全台逐時實際負載、CWA 天氣（[cwa_weather_store.py](../../src/shiro_mlops/data/cwa_weather_store.py)，以 `CWALocation` 作輸入、不讀全域 settings）、台電三個快照、已發布預報，以及預報實績配對（[forecast_track_record.py](../../src/shiro_mlops/data/forecast_track_record.py) 的 `ForecastTrackRecordStore`）。repository module 不再 re-export 各 store 類別。runner 的 `TaskRuntime` 只持有全台逐時實際負載與 CWA 天氣兩個 store，`ServedTasks` 改收 `TaskRuntime`，營運資料檢視器只取用 engine；API 啟動仍只建立一次 composition root。
> 與本節方向的差異：類別名 `TimeSeriesRepository` 與 Dagster resource key `time_series_repo` 不改，避免牽動約 30 處建構呼叫與 56 個測試檔；台電快照與已發布預報的 store 沿用既有類別名，方法縮為 `upsert`／`fetch`／`insert`／`fetch_latest` 等，CWA 天氣 store 沿用原方法名。
> 本節指向的程式位置（22 個 public 方法、`upsert_cwa_weather`、`resolve_weather` 以 `object` 標註的參數等）記錄檢視基準當時的狀態，僅供歷史參考；現行契約見 [data-contracts.md](../reference/data-contracts.md) §3 與 [ml-tasks.md](../reference/ml-tasks.md) §3。

### 現況與證據

[repository.py](../../src/shiro_mlops/data/repository.py) 是本期變動最多的檔案，因為負載、CWA 觀測、CWA 預報選版、跨 store 配對與四個 sibling store 都放在這裡。
`TimeSeriesRepository` 的 22 個 public 方法中，12 個沒有自己的邏輯：10 個轉呼叫 sibling store、1 個只會 raise 的 `upsert_cwa_weather`、1 個單筆轉呼叫。
台電三個快照的讀取方法在 src 中沒有呼叫端，只用於測試讀回。
每加一張表就要加轉呼叫（`c7cd102` 加 12 行、`20662dd` 加 4 行）；呼叫端已改用自訂 Protocol，或把參數型別寫成 `object`（[weather_resolution.py](../../src/shiro_mlops/data/weather_resolution.py)），表達「只需要其中一塊」。

### 加深方向與取捨

```text
Before：TimeSeriesRepository〔22 個 public 方法，12 個 pass-through〕
After ：composition root〔一個 engine、一次 schema init〕→ 交出 store：全台逐時實際負載（候選 3）、CWA 天氣、台電快照、已發布預報
```

- **depth 與 deletion test**：12 個 pass-through 刪除後複雜度不會在別處重現；真正值得保留的只有 composition（單一 engine、單次 schema init、單一 Dagster resource）。
- **locality／leverage**：呼叫端依賴自己用到的 store，取代自訂 Protocol；新增表不再改 facade。
- **seam／adapter**：local-substitutable。跨 store 配對移到預報實績 module。
- **成本與限制**：單獨做只是搬方法，不增加 depth；應排在候選 2、3 之後收尾。CWA 天氣 store 改以 `CWALocation` 作輸入、不讀全域 settings；其餘選版詞彙仍等 [#102](https://github.com/shiroki9979/shiro-mlops/issues/102) 的觸發條件。

### 測試保留重點

快照與已發布預報的讀回測試直接打各 store；runner 與腳本的 fake 只需模擬單一 store。
`upsert_cwa_weather` 的拒絕測試可刪除；facade 初始化測試保留。

## 未列入的觀察

- **訓練表自帶天氣識別（Speculative）**：只重跑 `{task_id}__model` 而任務設定的代表點或權重已改時，可能以舊的加權天氣訓練；實務上 features 與 model 一起跑，風險低。lab 快照已檢查天氣識別。
- **CWA 天氣讀取詞彙**：`fetch_weather_range` 讀全域 `settings.cwa_locations` 做 alias 與測站互轉；canonical 欄名到特徵欄名的對映出現在三處，預報產品 id 與角色出現在四處。證據補充於 [#102](https://github.com/shiroki9979/shiro-mlops/issues/102)，仍等其觸發條件。
  **狀態（2026-11-23）**：讀全域 settings 一句記錄檢視基準當時的狀態；[#315](https://github.com/shiroki9979/shiro-mlops/issues/315) 已讓 `fetch_weather_range` 直接收 `CWALocation`，CWA 天氣 store 不再讀全域 settings。欄名對映與預報產品詞彙的重複仍在，照舊等 #102。
- **死碼**：`cwa_client._parse_cwa_observations_payload` 與 `CWAClient.forecast_url` 在 src 與 tests 都沒有呼叫端，可直接刪除。
- **用語**：`direct_classification` 的 `lead_hours` 自負載起點起算，與 GLOSSARY「提前時數」不同，目前只是命名風險。

## 已有足夠 depth 的 module

`tasks/model_store.py`、`tasks/definition.py`、`tasks/accumulation.py`、`tasks/weighted_weather.py`、三個任務類型、
`data/hourly_actual_load.py` 的純函式、CWA 與台電的 parse 函式、`core/io_managers.py`、`core/database.py` 的 `ensure_timescale_hypertables`、
`service/data_explorer/cursor.py`、`core/forecast_view_publisher.py`（本機與 S3 兩個 adapter）。
`pipelines/smoke_check.py` 重述排程契約是刻意的 drift 偵測，不建議收斂。

## 既有決策與保留項目

領域名稱依 [GLOSSARY.md](../../GLOSSARY.md)，行為契約依 [Reference 文件](../reference/)。
8 個候選皆與現行 ADR 一致，沒有需要重開的 ADR；候選 1、3 分別落實 [ADR-0009](../adr/0009-decouple-ml-tasks-via-task-config-and-task-types.md)（共用元件歸 runner）與 [ADR-0008](../adr/0008-derive-hourly-actual-load-from-regional-snapshots.md) §4（只讀推算口徑）。

## 檢視證據的範圍

本次以閱讀程式與 `git log` 為主，未執行測試套件或 PostgreSQL 實機驗證。
呼叫端數、patch 次數與 commit 數以檢視基準上的 `grep` 與 `git log` 計得；檢視基準至 `b6c549e` 之間 `src/` 與 `lab/` 沒有變動。
候選 1 的「NaN 視同 0」以合成資料訓練的 LightGBM 模型驗證，尚未以正式模型重現。
候選 2 的 session TimeZone 風險未驗證。
