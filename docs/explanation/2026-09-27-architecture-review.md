<!-- markdownlint-disable MD024 -->
# 架構檢視：module 加深候選紀錄

- 建立日期：2026-09-27
- 最後更新：2026-09-27
- 文件類型：Explanation（架構現況與取捨分析）
- 狀態：待評估；尚未選定實作候選或定義新 interface
- 檢視基準：`da538a58433a3e00ccf84dee19f7de9679c02e0e`

## 範圍與結論

本次沿最近 80 個非 merge commits（2026-09-03 至 2026-09-27）追查變更熱點，
聚焦營運資料檢視器、氣象署鄉鎮預報版本與全台逐時實際負載。
`repository.py`、`assets.py` 與 `weather_resolution.py` 分別出現在 22、20、7 個 commits。
判斷依據為實際呼叫流程、歷史修補與現有測試，屬有範圍的架構檢視。

| 候選 | 建議強度 | 主要收益 | 建議時機 |
| :--- | :--- | :--- | :--- |
| 1. 集中營運資料檢視器的分頁規則 | Strong | 同一排序規則控制 cursor 與查詢，涵蓋 8 個 datasets | 優先深入評估 |
| 2. 集中預報版本選取與降級解析 | Worth exploring | 預報消費政策具有共同 locality | 確認後續政策變更需要共同修改時 |
| 3. 收攏營運資料檢視器的查詢生命週期 | Worth exploring | 畫面操作共用窗口與 cursor 有效性規則 | 下次新增篩選或查詢操作時 |

優先建議候選 1：相同排序 invariant 曾需三處同步修補，已有具體維護成本；
沿用既有 list interface 與離線 fixture 即可驗證改善，範圍也較候選 2 容易控制。
此排序為評估建議，尚未形成實作承諾。

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

領域名稱依 [CONTEXT.md](../../CONTEXT.md)，行為契約依 [SPEC.md](../SPEC.md)。三項候選均須維持：

- [ADR-0006](../adr/0006-timescaledb-local-storage-layer.md)：地端 TimescaleDB 與 Parquet／Feast 分工。
- [ADR-0007](../adr/0007-isolate-cwa-access-behind-scheduled-ingestion.md)：CWA 只經排程入庫，預報消費 canonical 資料；ingestion 新鮮度與預報七小時 stale 規則分開。
- [ADR-0008](../adr/0008-derive-hourly-actual-load-from-regional-snapshots.md)：全台逐時實際負載來源與舊列隔離；負載起點過舊時拒絕預報，氣象版本以請求時間判斷可用性。

已有足夠 depth、應保留的 module 包括 DatasetReader 的 list interface、
全台逐時實際負載推算，以及排程、asset 與 smoke check 共用的訓練就緒檢查。
本次尚無需要重開 ADR 的衝突；新 interface 與具體 implementation 留待候選選定後討論。

## 檢視時的驗證紀錄

2026-09-27 架構檢視時，下列後端 50 項測試通過：

```bash
uv run --no-sync pytest \
  tests/unit/test_weather_resolution.py \
  tests/unit/test_cwa_ingestion.py \
  tests/unit/test_data_explorer_cursor.py \
  tests/unit/test_data_explorer_query.py \
  tests/unit/test_data_explorer_hourly_load.py \
  tests/unit/test_data_explorer_weather.py \
  tests/unit/test_data_explorer_power.py -q
```

前端 13 項操作測試通過，另有圖表零尺寸警告：

```bash
# Working directory: frontend/
pnpm exec vitest run tests/integration/data-explorer.test.tsx
```

引用的 `test_data_explorer_api.py` 案例已閱讀，未包含於上述執行範圍。
本次未執行完整測試套件或 PostgreSQL 實機驗證；通過的既有測試不代表候選重構已完成。

## 後續待決事項

選定候選後，再確認責任範圍、interface、internal seam、測試保留方式與最小變更切片。
若需修訂既有 ADR，應另行記錄決策理由。
本文件保存候選與證據，後續狀態可由 [ROADMAP.md](../ROADMAP.md) 追蹤。
