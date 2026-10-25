<!-- markdownlint-disable MD024 -->
# 架構檢視：module 加深候選紀錄

- 建立日期：2026-09-27
- 最後更新：2026-10-25
- 文件類型：Explanation（架構現況與取捨分析）
- 狀態：候選 1 已依規格實作並完成雙資料庫驗收；候選 2、3 待評估
- 候選 1 規格：[GitHub #72](https://github.com/shiroki9979/shiro-mlops/issues/72)
- 檢視基準：`da538a58433a3e00ccf84dee19f7de9679c02e0e`

## 範圍與結論

本次沿最近 80 個非 merge commits（2026-09-03 至 2026-09-27）追查變更熱點，
聚焦營運資料檢視器、氣象署鄉鎮預報版本與全台逐時實際負載。
`repository.py`、`assets.py` 與 `weather_resolution.py` 分別出現在 22、20、7 個 commits。
判斷依據為實際呼叫流程、歷史修補與現有測試，屬有範圍的架構檢視。

| 候選 | 建議強度 | 主要收益 | 建議時機 |
| :--- | :--- | :--- | :--- |
| 1. 集中營運資料檢視器的分頁規則 | Strong | 同一排序規則控制 cursor 與查詢，涵蓋 8 個 datasets | 已實作並驗收 |
| 2. 集中預報版本選取與降級解析 | Worth exploring | 預報消費政策具有共同 locality | 確認後續政策變更需要共同修改時 |
| 3. 收攏營運資料檢視器的查詢生命週期 | Worth exploring | 畫面操作共用窗口與 cursor 有效性規則 | 下次新增篩選或查詢操作時 |

優先建議候選 1：相同排序 invariant 曾需三處同步修補，已有具體維護成本；
沿用既有 list interface 與離線 fixture 即可驗證改善，範圍也較候選 2 容易控制。
2026-09-27 已選定候選 1，並確認 Q1 至 Q8 的設計選擇；完整方案已整理為 GitHub 規格 #72，五張工單已確認並發布為 #73 至 #77。

## 評估用語

- **module／interface／implementation**：module 透過 interface 提供行為；interface 包含呼叫端必須知道的順序、限制與錯誤，implementation 封裝內部工作。
- **depth／deep／shallow**：以少量 interface 知識取得較多行為即有 depth；deep module 隱藏複雜度，shallow module 則讓呼叫端承擔過多 implementation 知識。
- **seam／adapter**：seam 是可替換行為的位置；adapter 是在該處提供 interface 行為的具體實作。已有真實替換需求才值得新增 seam。
- **locality／leverage**：locality 使規則、修改與驗證集中；leverage 使多個呼叫端共用同一份行為。
- **deletion test**：檢查移除某個 module 或呼叫端責任後，複雜度是否消失、集中，或散回其他呼叫端；檔案短小本身不代表 shallow。

## 候選 1：集中營運資料檢視器的分頁規則

### 現況與證據

排序 invariant 分散於 [specs.py](../../src/shiro_mlops/service/data_explorer/specs.py) 的 `sort`、
各 reader 傳給 `apply_cursor` 的欄位 tuple，以及 SQL 的 `ORDER BY`。
[query.py](../../src/shiro_mlops/service/data_explorer/query.py) 與
[pagination.py](../../src/shiro_mlops/service/data_explorer/pagination.py) 另負責 cursor 解碼與時間轉換。

`c3be008` 為避免只有 `valid_to` 不同的預報列漏頁，曾同時修改上述三處排序宣告；
`c75092a` 修正 cursor 的 aware／naive UTC 比較。
目前 [ForecastReader](../../src/shiro_mlops/service/data_explorer/weather.py) 仍須傳入 dialect，
決定是否套用 SQLite 時間正規化。
這些是已修補問題所揭露的維護摩擦，並非本次重現仍存在的漏頁缺陷。

### 加深方向與取捨

由既有分頁 module 統一持有排序、cursor key 與時間比較規則；
[hourly_load.py](../../src/shiro_mlops/service/data_explorer/hourly_load.py)、
[power.py](../../src/shiro_mlops/service/data_explorer/power.py) 與氣象 reader
保留 dataset 特有的篩選及資料投影。

```text
Before：specs.sort ↔ reader cursor tuple ↔ SQL ORDER BY
After ：reader 的資料集規則 → 分頁 module〔排序／cursor／時間比較〕→ 結果
```

- **depth 與 deletion test**：既有 list interface 已有 depth；應收回 internal interface 洩漏的同步責任。刪除共用分頁 module 會把複雜度散回 8 個 readers，應保留。
- **locality／leverage**：一處排序變更同時控制 cursor 與查詢，8 個 datasets 共用修正。
- **seam／adapter**：沿用注入 SQLAlchemy Engine 的 seam 與既有 SQL adapter；正式 PostgreSQL 與 SQLite fixture 已有實際環境差異。
- **成本與限制**：須保留各 dataset 複合鍵；範圍限於現有 newest-first keyset 契約，避免擴張成任意 SQL builder。SQLite 測試無法替代 PostgreSQL 方言驗證。

### 測試保留重點

沿用 [test_data_explorer_api.py](../../tests/integration/test_data_explorer_api.py) 中固定時間窗口、
新增預報版本後仍停留原版本，以及僅 `valid_to` 不同仍可完整跨頁的案例。
透過 [逐時負載 reader 測試](../../tests/unit/test_data_explorer_hourly_load.py) 的 list interface
驗證無重複、無遺漏；避免綁定內部 SQL 組裝方式。

## 候選 2：集中預報版本選取與降級解析

### 現況與證據

[repository.py](../../src/shiro_mlops/data/repository.py) 的 `fetch_cwa_forecast_rows`
提供 7 個查詢選項，且只有 `geocode` 與 `issued_before` 同時存在時才啟用版本選取政策。
[weather_resolution.py](../../src/shiro_mlops/data/weather_resolution.py) 再負責最新列、插值、
stale 判定與降級；呼叫端須把同一 `as_of` 分別傳入發布與更新 cutoff，並要求相鄰點。
`a732ae9` 曾同時修補相鄰點查詢與 observation cutoff。

### 加深方向與取捨

讓供預報消費的版本選取、查詢範圍與逐時解析由同一 module 負責，
保留既有解析入口與 SQL 有界查詢。

```text
Before：repository〔版本回退／相鄰點〕↔ resolver〔投影／stale／降級〕
After ：既有解析 interface → 天氣解析 module〔選版／查詢範圍／逐欄來源〕
```

- **depth 與 deletion test**：`resolve_weather` 已是 deep module；刪除它會使正常／降級規則散回呼叫端。值得吸收的是偏 shallow 的查詢搭配協議，單純搬動 SQL 不會增加 depth。
- **locality／leverage**：將選版與投影政策集中，讓就緒檢查與動態視界預報共用。
- **seam／adapter**：保留既有儲存 seam 與 SQL adapter；無須為單一 implementation 新增 Protocol。
- **成本與限制**：搬移成本高於候選 1；應先確認哪些政策確實經常共同修改。營運資料檢視器的版本瀏覽仍具有獨立語意。

### 測試保留重點

[test_weather_resolution.py](../../tests/unit/test_weather_resolution.py) 已有 SQLite fixture
穿過 repository 與 resolver 的插值測試；
[test_cwa_ingestion.py](../../tests/unit/test_cwa_ingestion.py) 已驗證新版缺少指定鄉鎮時退回舊完整版本。
後續可透過解析 interface 串接「版本回退 → 逐欄結果與來源」的驗證，
逐步取代僅檢查 query kwargs 的測試；既有儲存行為測試仍須保留。

## 候選 3：收攏營運資料檢視器的查詢生命週期

### 現況與證據

[use-explorer-search.ts](../../frontend/src/components/data-explorer/use-explorer-search.ts)
集中 URL 合併與預設窗口，但
[explorer-filters.tsx](../../frontend/src/components/data-explorer/explorer-filters.tsx)
仍有 3 處輸入事件自行傳入 `cursor: undefined`；
[explorer-page.tsx](../../frontend/src/components/data-explorer/explorer-page.tsx) 負責翻頁與刷新協調。

`da538a5` 已修正開啟明細後重新 render 使預設窗口漂移，以及 Refresh 未同步更新營運狀態的問題。
這些歷史修補顯示查詢生命週期知識跨越數個 module；新增篩選仍需再次理解 cursor invariant。

### 加深方向與取捨

將固定窗口、cursor 失效與 URL 同步收進既有查詢 module，讓畫面表達使用者操作。
刷新協調可在後續評估是否屬於同一責任，避免把全部畫面狀態一併集中。

```text
Before：Search hook〔窗口／URL〕↔ Filters〔清 cursor〕↔ Page〔翻頁／刷新〕
After ：畫面操作 → 查詢 module〔窗口／cursor 有效性／URL〕→ 既有 router
```

- **depth 與 deletion test**：generic patch interface 偏 shallow；收回重複的 cursor 重置知識可增加 depth。直接把 hook inline 到頁面，或新增原樣轉傳的 module，皆不會改善 locality。
- **locality／leverage**：各篩選操作共用有效性規則；多個 datasets 使用同一頁面，但目前實際頁面呼叫端只有一個，收益有限。
- **seam／adapter**：此為 in-process 規則；沿用 router 與 HTTP／MSW 測試 adapter 即可，無須新增抽象 seam 或狀態機套件。
- **成本與限制**：應以減少呼叫端必須知道的規則為限；過度整合會把 router 與 query cache 綁在一起，適合隨下一次相關變更進行。

### 測試保留重點

保留 [data-explorer.test.tsx](../../frontend/tests/integration/data-explorer.test.tsx)
中開啟明細後窗口固定、翻頁、URL 篩選與刷新營運狀態的操作測試。
後續補強「下一頁後修改篩選回到第一頁」的使用者行為；interface 是測試面，無須另測 patch 物件形狀。

## 既有決策與保留項目

領域名稱依 [GLOSSARY.md](../../GLOSSARY.md)，行為契約依 [SPEC.md](../SPEC.md)。三項候選均須維持：

- [ADR-0006](../adr/0006-timescaledb-local-storage-layer.md)：地端 TimescaleDB 與 Parquet／Feast 分工。
- [ADR-0007](../adr/0007-isolate-cwa-access-behind-scheduled-ingestion.md)：CWA 只經排程入庫，預報消費 canonical 資料；ingestion 新鮮度與預報七小時 stale 規則分開。
- [ADR-0008](../adr/0008-derive-hourly-actual-load-from-regional-snapshots.md)：全台逐時實際負載來源與舊列隔離；負載起點過舊時拒絕預報，氣象版本以請求時間判斷可用性。

已有足夠 depth、應保留的 module 包括 DatasetReader 的 list interface、
全台逐時實際負載推算，以及排程、asset 與 smoke check 共用的訓練就緒檢查。
本次尚無需要重開 ADR 的衝突；候選 1 的 interface 方向與交付要求記錄於後續設計討論。

## 檢視證據的範圍

2026-09-27 架構檢視時，只執行資料檢視器與天氣解析相關的後端單元測試，以及資料檢視器前端操作測試；`test_data_explorer_api.py` 案例僅閱讀。
當時未執行完整測試套件或 PostgreSQL 實機驗證；通過的既有測試不代表候選重構已完成。

## 候選 1 設計方案（規格已發布）

### 候選 1：已確認的設計方向

2026-09-27 設計討論已確認：

| 問題 | 選擇 | 決定 |
| :--- | :--- | :--- |
| Q1：分頁 module 的責任 | B | 集中排序、keyset 比較、cursor 編解碼與時間正規化；reader 保留資料集篩選及結果投影。 |
| Q2：交付範圍 | A | 最終交付涵蓋全部 8 個 datasets；實作過程可分切片遷移。 |
| Q3：資料列時間精度 | A | 本次納入精度修正，先建立重現測試；排序與 cursor 保留原始時間精度，畫面可維持整秒顯示。 |
| Q4：真實資料庫驗收 | A | 交付須通過隔離的本機 PostgreSQL／TimescaleDB 分頁測試；日常 CI 維持現有離線流程。 |
| Q5：舊 cursor 相容策略 | A | 全部 datasets 統一升為 v2；v1 cursor 一律回傳 HTTP 400，使用者重新查詢第一頁。 |
| Q6：舊 cursor 的畫面恢復操作 | A | 新增「Back to first page」按鈕，清除 cursor，保留目前畫面的時間窗口與篩選條件。 |
| Q7：分頁 module 的 interface | C | 加深既有 `DatasetReader.list(params)`，統一分頁生命週期；reader 提供資料選取、filters 與整頁 projection。 |
| Q8：精確時間窗口 | A | 本次移除起訖各放寬一秒的補償，使用精確閉區間 `[start, end]`；同步驗證列表與完整度查詢在兩種資料庫的端點、微秒及缺口判斷。 |

以上八項選擇均已確認；2026-09-27 發布規格 #72 與工單 #73 至 #77，並完成實作。重跑方式見[操作文件](../how-to/verify-data-explorer-pagination.md)。

### 候選 1：相容性與時間精度的查證

- [cursor.py](../../src/shiro_mlops/service/data_explorer/cursor.py) 的 v1 token 保存版本、dataset、filters 與最後排序鍵。排序宣告的位置不在 token 內；若鍵值與比較語意不變，單純集中責任不必升版。
- [pagination.py](../../src/shiro_mlops/service/data_explorer/pagination.py) 從已格式化的回傳 item 建立下一頁 key；[timefmt.py](../../src/shiro_mlops/service/data_explorer/timefmt.py) 預設只輸出整秒，資料列的小數秒可能在此遺失。
- v1 token 未另存原始列識別資訊；觀測批次審計只以 `fetched_at` 為 key，同秒不同微秒的兩列可能產生相同 token，無法一般性無損復原原先的分頁位置。入庫批次使用 `datetime.now()`，儲存亦未移除微秒；此風險並非僅來自不符合契約的輸入，實際列表漏列仍待重現測試確認。
- SQLite 的 `datetime(...)` 亦將小數秒化為整秒，目前只在預報 reader 的 cursor 比較啟用，SQL 排序則仍使用原始欄位。已查證兩種運算的精度差異，尚未重現實際列表漏列。
- 現有測試覆蓋 filter 時間窗的小數秒及預報 `valid_to` 複合鍵；此輪搜尋未見資料列 sort key 的微秒跨頁案例。
- [TimescaleDB 測試](../../tests/integration/test_timescaledb_repository.py) 有 `TIMESCALE_INTEGRATION_URI` opt-in 入口；未設定時略過。[CI](../../.github/workflows/ci.yml) 未配置該資料庫，現有真實資料庫案例亦未涵蓋營運資料檢視器分頁。
- `TimeWindow.as_utc()` 為補償 SQLite 格式比較而將起訖各放寬一秒，實際上同時影響 PostgreSQL、全部 8 個列表，以及 `hourly_gaps`、`observation_gaps`、`ten_minute_gaps`、`regional_slot_map`。未找到允許窗口外資料的契約；Q8 已決定一併修正，且須保留上下界資料正確納入的驗證。

### 候選 1：interface 比較（已選 C）

三案均保留外部 `DatasetReader.list(params)`，透過既有 SQL adapter 執行有界查詢，
並在顯示投影前取得最後一筆可見原始列的完整排序鍵。

| 方案 | interface 與 seam | depth／locality 取捨 |
| :--- | :--- | :--- |
| A：獨立分頁 module | reader 提供查詢來源、參數與整頁投影，交由單一 `paginate` 入口執行。 | 分頁流程集中且可獨立使用；新增查詢來源物件與 callback 協議。 |
| B：兩階段查詢計畫 | 分頁 module 補入排序與 cursor 條件，reader 執行查詢後再交回完成分頁。 | 執行方式較彈性，但呼叫端須遵守步驟順序與查詢不可再修改的規則，depth 較小。 |
| C：加深既有 DatasetReader | `list(params)` 統一生命週期；reader 提供可信資料選取、filters 與整頁 projection，預報保留版本解析 hook。 | 沿用既有 seam，分頁 locality 集中且新增結構較少；reader 作者須理解固定 hook 契約。 |

已選定 C。八個 reader 已共用 `DatasetReader`，可直接收回 SQL 排序、
跨頁比較、`limit + 1`、完整原始鍵擷取與 v2 cursor 的協調責任。
整頁 projection 保留區域完整度補查與全時間窗 `missing_slots`，須維持可見列的筆數與順序；
完整度篩選仍先在資料查詢生效。測試跨 `list` seam 驗證行為，不綁定 hook 呼叫次序。

### 候選 1：module 責任與執行順序

外部 interface 保留 `DatasetReader(engine).list(params) -> ListEnvelope`。
reader 的 internal interface 由資料集識別、可信 `SELECT ... FROM`、
`filters(query)` 與 `project(query, rows)` 組成；預報 reader 保留 `build_query(params)`
以解析或恢復已釘選版本。方法名稱可依最小實作調整，責任固定如下：

1. 共用流程驗證 cursor 版本與格式、建立 query，恢復固定時間窗口與必要版本篩選，並驗證 filters 綁定。
2. reader 提供完整資料集篩選；分頁 module 以單一排序宣告產生相同語意的 `ORDER BY` 與 keyset 比較，加入 `limit + 1` 後查詢。
3. 分頁 module 截取可見列，從最後可見的原始列保留完整排序鍵，再交給 reader 進行整頁 projection；projection 保持列數與順序。
4. 共用流程產生 v2 cursor 與既有 envelope；預報版本釘選資訊亦保留完整原始時間精度。

原始鍵、SQL 方言與時間比較均位於共用 implementation；reader 使用既有 SQL adapter
完成資料集特有查詢與補充資料。新增排序鍵時只修改其共用宣告與對應測試，
不再要求同步修改 reader 的排序與 cursor 欄位 tuple。
所有查詢值繼續參數化，資料表與欄位名稱來自可信程式碼。

`CursorError`、無效查詢與資料庫不可用仍沿用 400、422、503 的對外語意。
沿用逐次請求讀取與既有 keyset 行為；跨頁完整性驗收採固定 fixture，
時間窗口與預報版本釘選不新增資料庫 snapshot 隔離。

### 候選 1：交付範圍

交付切片、驗收條件與工單阻擋關係以 [GitHub #72](https://github.com/shiroki9979/shiro-mlops/issues/72) 及 #73 至 #77 為準，本文件不重複保存。
八個列表與四種完整度已在 SQLite 與隔離本機 TimescaleDB 驗收；v2 拒絕 v1，且無 v1 相容層。
重跑方式見[操作文件](../how-to/verify-data-explorer-pagination.md)；若需修訂既有 ADR，應另行記錄決策理由。
