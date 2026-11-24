# 營運資料檢視器 (Data Explorer)

> - Created: 2026-11-20
> - Last Updated: 2026-11-24

> 由 `docs/SPEC.md` 第 4 節拆出。

---

> **狀態：已實作。** 本節定義 [GitHub #40](https://github.com/shiroki9979/shiro-mlops/issues/40)
> 與子工單 #41–#50 的契約；`GET /data/*` 與前端 `/data` 路由僅在 local environment 或 `DATA_EXPLORER_ENABLED` 時可用。

## 1. 產品邊界

- **主要用途**：讓營運人員確認 ingestion 是否成功、資料是否完整或過期，檢視實際入庫內容，並以趨勢、聚合與分組比較探索資料。
- **使用者**：僅限本機或受信任內網中的工程師。
- **作業模式**：唯讀；不得透過 Data Explorer 觸發 ingestion、修改或刪除資料。
- **非目標**：不作為模型訓練工具、通用資料庫管理器或公開雲端服務；模型訓練與回測屬於 `lab/`（[ADR-0011](../adr/0011-co-locate-lab-workspace-with-unidirectional-dependency.md)）。

## 2. 資料與呈現邊界

- **領域資料集**：以逐時用電負載、全台供需、區域供需、機組發電、CWA 測站觀測與 CWA 鄉鎮預報六個 canonical typed datasets 為主要檢視單位。
- **逐時負載檢視口徑**：列表、缺口與狀態僅讀取 `source = 'regional_snapshot_sum'` 的推算列；升級期間尚未清除的 d015046 舊列不得出現在 canonical 檢視或影響新鮮度與完整度。
- **Ingestion audit**：納入 CWA 觀測批次與預報版本兩個 audit datasets，顯示狀態、擷取時間與缺少的測站或行政區；不回傳完整 `raw_payload`。
- **排除資料**：v1 不顯示完整 `raw_payload`、`legacy_cwa_weather` 歸檔與 Feast derived features。
- **呈現模型**：以領域資料集名稱、領域欄位、單位與專屬篩選條件組織介面；不將實體資料表名與任意資料庫 schema 當作使用者介面。

## 3. 導覽與查詢行為

- **頂層導覽**：Data Explorer 屬於工程主控台，使用獨立 `/console/data` 路由；`/console/monitoring` 專注於健康與新鮮度摘要，並可連結至對應資料集的篩選結果。前端路由皆在工程主控台的 base path `/console/` 之下（[ADR-0014](../adr/0014-keep-engineering-console-local-and-split-frontend-apps.md) §2.5），本文件其餘段落省略此前綴。
- **排序與分頁**：八個列表以各資料集固定的完整複合鍵降冪排序，使用 v2 server-side keyset cursor；排序、翻頁比較與 cursor 均保留原始微秒精度。API 每頁預設 50 筆、上限 200 筆，不提供無界全表載入；工程主控台的列表請求固定帶 `limit=200`，區域供需一天的快照約 3 頁可看完，不提供每頁筆數選單。
- **時間窗口**：列表與完整度查詢共用精確閉區間 `[start, end]`；兩端點納入、窗口外一微秒排除，`start = end` 合法。cursor 固定第一次解析的窗口，頁面顯示時間維持既有整秒格式。窗口可長於該資料集的列表上限（§7），此時只有圖表涵蓋整個窗口：前端不送 list 請求，表格位置改顯示「目前窗口超過明細上限 N 天，請在圖上框選或縮小窗口以檢視明細」（字典鍵 `explorer.results.detailLimitExceeded`），CSV 匯出停用，Refresh 也不重新取得列表；URL 中的 cursor 此時不採用，並在下一次操作時自 URL 移除。判定與 API 的 422 規則相同：終點減起點大於 N 天才算超過，剛好 N 天不算。
- **歷史可達性**：使用者可透過有界時間範圍與 cursor 逐頁檢視所有保留中的歷史資料。
- **時間呈現**：API 回傳帶 `+08:00` offset 的 RFC 3339 timestamp；介面明示時區為 `Asia/Taipei`。
- **功率單位**：介面以 MW 為主要顯示單位；對於以萬瓩儲存的全台與區域供需 typed values，在明細或 tooltip 同時顯示儲存值，並依 `1 萬瓩 = 10 MW` 轉換。
- **預報版本**：CWA 鄉鎮預報預設顯示最新發布版本；可以 `dataset_id`、`issued_at`、`source_updated_at` 與 `geocode` 篩選所有已保存 forecast vintages。v1 不另建 Effective Serving View。

## 4. 營運狀態語意

- **新鮮度**：每個 dataset 依自身預期更新頻率判定；超過兩個預期更新週期未取得新資料時顯示 warning。CWA forecast ingestion 新鮮度與 serving 使用的七小時 stale 規則必須分開顯示，不得混為同一狀態。
- **全台供需完整度**：每個 observation slot 預期一筆資料。
- **區域供需完整度**：每個 observation slot 預期同時具備北、中、南、東四區；缺少任一區即標記該 slot 不完整。列表的 `missing_slots` 以整個查詢窗口計算：窗口內每個預期的 10 分鐘時段只要不足四區（包含四區全缺、沒有任何資料列的時段）即列為缺口，結果不隨分頁或 `region`／`completeness` 篩選變動，口徑與逐時負載、全台供需、測站觀測一致。`GET /data/status` 仍只判定最新一個 slot 缺少的區域。
- **列表缺口範圍**：`missing_slots` 只檢查已發生的預期時段，即 `min(end, 現在)` 之前；窗口延伸到未來時，尚未到來的時段不列為缺口。逐時負載只檢查到最近一個已完成的小時。各列表的 `missing_slots` 以時間遞增排列。只有逐時負載的 `subject` 與測站觀測的 `station_id` 篩選縮小缺口範圍（只檢查該預測對象或該測站），其他篩選不改變 `missing_slots`；每個篩選是否縮小缺口宣告在資料集定義上。
- **CWA 完整度**：以 allowlist 與 observation batch／forecast release audit header 判定缺少的測站或行政區。測站觀測、鄉鎮預報與兩個 audit datasets 在 `GET /data/status` 的 `completeness` 與 `missing_identifiers` 只看最新 header 的缺漏清單（`missing_station_ids`、`missing_geocodes`）：清單為空即完整，否則不完整並列出清單。Audit 列表項目、`status` 篩選與狀態時間軸的 `status` 也由同一份缺漏清單推導（清單為空為 `complete`，否則為 `incomplete`），推導在 SQL 內完成，使用 CWA 擷取模組（`shiro_mlops.data.cwa_client`）提供的 SQL 形式：與擷取端的 Python 推導是同一規則的兩種形式，SQLite 與 TimescaleDB 共用同一個運算式；header 表不保存完整度欄位。
- **逐時負載完整度**：在查詢時間區間內檢查預期的逐小時時間點，並揭露缺口。
- **機組完整度**：機組數量可變，不以固定筆數判定失敗。
- **空值語意**：資料契約允許的 nullable 欄位不得僅因為值為 `NULL` 就標記 dataset 不完整。

## 5. 介面與 API 邊界

- **前端路由**：在 `/console/` 之下提供 `/data/power/load`、`/data/power/supply-demand`、`/data/power/regional`、`/data/power/units`、`/data/weather/observations`、`/data/weather/forecasts` 與 `/data/audits` nested routes，支援重新整理與 deep link。側邊欄在 Data Explorer 啟用時列出上述資料集與 CWA audits。`GET /data/status` 回傳的 `href` 是不含 base path 的工程主控台路由（如 `/data/power/load`），前端產生連結時補上 `/console`。
- **資料 API**：每個領域 dataset 使用獨立 typed read endpoint：`GET /data/power/load`、`GET /data/power/supply-demand`、`GET /data/power/regional`、`GET /data/power/units`、`GET /data/weather/observations`、`GET /data/weather/forecasts`、`GET /data/audits/cwa-observations` 與 `GET /data/audits/cwa-forecasts`。所有 list endpoints 共用 cursor pagination response envelope。圖表另以 list 路徑加 `/series` 的有界序列 endpoint 讀取（目前為 `GET /data/power/load/series`、`GET /data/power/supply-demand/series`、`GET /data/power/regional/series`、`GET /data/power/units/series`、`GET /data/weather/observations/series`、`GET /data/weather/forecasts/series`、`GET /data/audits/cwa-observations/series` 與 `GET /data/audits/cwa-forecasts/series`），契約見 [rest-api.md](rest-api.md) §5。兩者都不提供任意 SQL 或任意實體資料表查詢。
- **Audit 呈現**：CWA observation 與 forecast 資料頁顯示最新 audit 狀態及 Audit History 連結；`/data/audits` 提供批次歷史與 missing identifiers，但不提供完整 `raw_payload`。

## 6. 交互與診斷行為

- **Freshness 維度**：分別顯示 ingestion age 與 source age。前者表示距上次成功入庫所經時間，後者表示最新來源事件或發布時間距今時間；不得以其中一者取代另一者。
- **資料表與明細**：列表只顯示核心營運欄位；點擊資料列後以 drawer 顯示該筆所有 typed fields。Data Explorer 表格採緊湊列距（列高約為共用表格預設的 60%），表格區塊高度受限並於內部捲動，表頭固定在上方；緊湊列距與固定表頭只套用於 Data Explorer，共用表格元件預設值與 Forecast View 表格外觀不變。數值欄靠右對齊並使用 tabular-nums；等寬字體只用於數值與識別碼（測站編號、geocode、鄉鎮代碼），時間與文字欄位使用一般字體；單位只寫在欄標題。`slot_complete` 與 audit `status` 以沿用資料集狀態配色的徽章呈現（完整為綠、不完整為琥珀），`region`、`unit_type`、`dataset_id` 以中性 chip 呈現；徽章與 chip 內文與明細 drawer 相同。相鄰兩列首欄時間的台北日期不同時，中間插入日期分隔列（標示下方資料列的日期）；分隔列不可點選，不影響明細 drawer 與 CSV 匯出內容。
- **缺口清單**：有缺口時，列表上方顯示缺口時段數，展開後列出缺口區間。連續缺口依資料集節奏合併：逐時負載與測站觀測為 1 小時，全台與區域供需為 10 分鐘。每個區間標示起訖時段與長度（缺口時段數 × 節奏，如「11/20 03:00–05:00（3 小時）」）；測站觀測依測站編號分組。清單只供閱讀，點擊不改變窗口。
- **篩選條件**：所有 datasets 皆提供時間區間篩選；逐時負載另提供預測對象（`subject`，如 `nationwide`），區域供需提供 region 與完整度，機組發電提供 unit type 與 unit name，測站觀測提供 station，鄉鎮預報提供有效時間、dataset、geocode 與發布／更新版本，audits 提供 audit type、status 與 missing identifier。
  - **值集合固定的欄位**：`region`（北部、中部、南部、東部）、區域供需 `completeness` 與 audit `status`（`complete`、`incomplete`）使用下拉選單，第一個選項「不篩選」清除該篩選；選項以 API 原始值寫入 URL，`completeness` 與 `status` 的顯示文字隨介面語系。`all_vintages` 使用開關，開啟時 URL 與 list、series 請求一律寫 `true`，關閉時 URL 與請求都不帶這個篩選；手寫的 `1`、`yes`（不分大小寫）視為開啟，並在下一次操作時改寫為 `true`，`false`、`0` 與空值視為關閉。開關與圖表的必填 `geocode` 提示讀同一個解析結果。下拉與文字欄位清成空值即移除該篩選。
  - **值集合開放的欄位**：`subject`、`unit_type`、`unit_name`、`station_id`、`geocode`、`dataset_id`、`issued_at`、`source_updated_at` 與 `missing_*` 維持文字輸入；不提供列出 distinct 值的 endpoint。
- **預設窗口與 cursor 失效**：URL 未指定 `start`／`end` 時，前端以進入頁面當下計算預設窗口，同一次瀏覽內不隨重新繪製漂移，且不主動寫入 URL。變更窗口或任一篩選即清除 cursor 並回到第一頁；只有翻頁操作會設定 cursor。
  - **快速區間**：以點擊當下（取整秒）計算。過去方向的 datasets 提供「今天」（台北日 00:00:00 至 23:59:59）、「近 24 小時」、「近 7 天」、「明細上限」（結束於當下，長度為該資料集 list 的時間範圍上限：7、14 或 31 天，見 §7）、「近 30 天」與「近 92 天」；後兩者結束於當下，供圖表檢視長期趨勢，超過明細上限時表格改顯示明細上限提示（§3 時間窗口）。鄉鎮預報以有效時間為準、由現在往後，提供「未來 24 小時」、「未來 72 小時」、「未來 7 天」與「未來 14 天」；預設窗口維持「進入當下前 1 小時至後 72 小時」，保留正在生效的預報時段。
  - **平移**：窗口長度 L 為終點減起點再加 1 秒。`‹` 的新窗口為「起點減 L」至「起點減 1 秒」，`›` 的新窗口為「終點加 1 秒」至「終點加 L」；新窗口與原窗口相鄰且不重疊，例如「今天」按一次 `‹` 即為完整的昨天。
  - **框選**：在圖上按住並拖曳跨過至少兩個 bucket，放開後新窗口為「第一個選取 bucket 的起點」至「最後一個選取 bucket 的終點減 1 秒」；bucket 長度依圖表實際粒度，`1h` 為 1 小時、`1d` 為 1 個台北日、`raw` 為該資料集的節奏（逐時負載、測站觀測、鄉鎮預報與 audits 為 1 小時，全台、區域供需與機組為 10 分鐘）。例：`1h` 選取 03:00 至 05:00 得到 03:00:00 至 05:59:59；10 分鐘的 `raw` 選取 03:00 至 03:20 得到 03:00:00 至 03:29:59。由右往左拖曳結果相同；在同一個 bucket 按下又放開視為點擊，只顯示 tooltip，不改窗口；拖出繪圖區即取消。框選做在共用圖表容器，所有圖表類型都支援。
  - **URL 更新**：快速區間、平移與框選一次寫入 `start`／`end`（帶 `+08:00` 的 RFC 3339）並清除 cursor，保留圖表設定，與其他窗口變更走同一條路徑；起訖時間的精確輸入維持原本行為，逐端更新。
- **排序**：v1 固定以最新資料優先，不提供任意欄位的 server-side 排序。
- **更新**：Data Explorer 僅提供手動 Refresh 與最後取得時間；不自動改動正在檢視的歷史頁面或已展開明細。資料集狀態同樣不自動更新；監控頁與 Data Explorer 首頁沒有自己的 Refresh，由頁首的 Refresh 重新讀取正在顯示的資料集狀態（與 API 健康狀態一起）。起訖時間輸入框一律以台北時間顯示：URL 的 `start`／`end` 帶其他 offset（例如 `Z`）時換算成台北時間，不直接顯示字面上的時分。
- **CSV 匯出**：前端可將當前已載入頁面匯出為 CSV；不提供跨頁或無上限的 server-side export。
- **Monitoring 調整**：Monitoring 以 Data Source Status 摘要顯示每個資料集的 `overall`，有資料時另顯示 freshness 與 completeness、無資料時顯示「無資料」，並連結至 Data Explorer 對應資料集；不再提供 Feature Store Snapshot。讀取失敗與離線比照 Data Explorer 首頁的資料集狀態：已有資料時重新讀取失敗保留摘要並加一行更新失敗提示（字典鍵 `monitoring.sources.refreshFailed`），尚無資料或離線時顯示讀取失敗訊息。

## 7. 狀態、存取與失敗契約

- **Data Explorer 首頁**：`/data` 顯示全部 datasets 的最新來源時間、最新入庫時間、freshness、completeness 與明細連結。每張狀態卡另有一張 24 小時小圖，窗口以進入頁面當下為準、重新渲染不滑動，讓工程師不必點進資料集就能看出哪個資料集斷了或不正常。六個領域資料集畫 sparkline（無軸、無 tooltip，橫軸固定為整個窗口，資料停止時尾端留白）：逐時負載 `load_mw`、全台供需 `curr_load_mw`、區域供需 `load_mw` 四區各一條細線、機組發電 `net_generation_mw` 不分組總和（`group_by=none`）、測站觀測每站一條 `temperature_c`、鄉鎮預報未來 24 小時（`start` 為當下）最新版本每個 `geocode` 一條 `temperature_c`。sparkline 沿用圖表卡片的 series endpoint、集中配色與缺口規則：補值的 `null` 處線段斷開，鄉鎮預報不補值，線段連接相鄰的點。兩個 audit 卡片以 `bucket=1h` 讀取狀態計數，畫成 24 格每小時狀態格線，最後一格為當下所在小時：有任何非 `complete` 批次或版本為不完整，只有 `complete` 為完整，沒有紀錄的小時留空。首頁共發出 8 個 series 請求，粒度皆為 `auto`（audit 為 `1h`），只為 `GET /data/status` 列出的 dataset 發出；Monitoring 頁不顯示小圖。
- **首頁的讀取失敗與離線**：資料集狀態與小圖採資料優先，與資料頁的列表、圖表卡一致。已有資料時重新讀取失敗，保留狀態卡或小圖，並加一行更新失敗提示（字典鍵 `explorer.statusRefreshFailed`、`explorer.sparkline.refreshFailed`）；尚無資料時讀取失敗，資料集狀態顯示讀取失敗訊息，小圖顯示「失敗」。瀏覽器判定離線而暫停讀取時，比照讀取失敗呈現；恢復連線後自動重新讀取。小圖在 24 小時內沒有任何值時顯示「空」，audit 狀態格線沒有「空」，沒有紀錄的小時留空。
- **狀態 API**：`GET /data/status` 是 Monitoring、Data Explorer 首頁與各資料頁的共用狀態來源。Typed list endpoints 不重複計算狀態，並共用含 `items`、`next_cursor` 與 `has_more` 的 pagination envelope。
- **狀態模型**：每個 dataset 的狀態是以 `kind` 判別的兩種形狀之一，兩者都帶 `id`、`label`、`href` 與衍生的 `overall`。`kind: "empty"` 表示尚未有任何入庫資料，不判定新鮮度與完整度，沒有其他欄位，`overall` 恆為 `warning`。`kind: "populated"` 另帶 `freshness` (`fresh | warning`)、`completeness` (`complete | incomplete`)、`latest_source_at`、`latest_ingested_at`、`ingestion_age_seconds`、`source_age_seconds` 與 `missing_identifiers`，皆必填；`latest_release_stale` 為 `true | false | null`，`null` 表示該 dataset 不標示發布過期（語意見 [data-contracts.md](data-contracts.md)）。`overall` 為 `healthy | warning`：`warning` freshness 或 `incomplete` 對應 `warning`，否則為 `healthy`。前端在無資料時只顯示 `overall` 與「無資料」，不顯示新鮮度、完整度、時間與經過秒數，資料頁也不顯示最新審計。讀取失敗不是一種狀態，以 HTTP 503 回報（見 HTTP 語意）。
- **Cursor 契約**：八個列表只接受 v2 cursor。cursor 為 opaque、stateless 且與當前窗口及 filters 綁定的 keyset cursor，含最後一筆完整原始排序鍵與契約版本，不設時間期限。綁定的 filters 即該資料集宣告的篩選，與列表、series 接受的篩選出自同一份資料集定義；列表只接受 `start`、`end`、`limit`、`cursor` 與這些篩選，其他參數回 HTTP 422（見 HTTP 語意）。更改 filters、v1 或格式無效時回傳 HTTP 400。帶 cursor 的請求收到 400 時，前端顯示返回第一頁的恢復操作（字典鍵 `explorer.results.backToFirstPage`，顯示文字隨介面語系）；使用者點擊後清除 cursor，保留窗口與篩選。明確預報版本保留，隱含最新版本重新解析；422／503 不提供此恢復操作。
- **資料頁的讀取失敗**：列表與圖表卡已有資料時，Refresh 重新讀取失敗會保留已顯示的列或圖，並在上方加一行更新失敗提示（字典鍵 `explorer.results.refreshFailed`、`explorer.chart.refreshFailed`），提示沿用依錯誤種類決定的訊息；帶 cursor 的請求收到 400 時，不論畫面上是否仍有資料都顯示返回第一頁的恢復操作。瀏覽器判定離線時請求暫停，列表與圖表卡比照讀取失敗顯示一般的查詢失敗訊息，不顯示空結果；恢復連線後自動重新讀取。超過明細上限與鄉鎮預報圖缺 `geocode` 時查詢停用，只顯示各自的提示。
- **開啟條件**：v1 不建立應用層登入與 RBAC。Data Explorer 路由與 API 僅在 local environment 或明確啟用功能旗標時可用；非本機存取必須由內網或 reverse proxy 限制，並使用 same-origin CORS，不得依賴現有 `CORS *` 對外暴露。
- **顯示範圍**：提供狀態、資料表、篩選、typed detail drawer、當頁 CSV 匯出、首頁的 24 小時小圖，以及八個資料頁表格上方的趨勢圖卡片（六個領域資料集與兩個 CWA audit，語意見 §8）。
- **HTTP 語意**：無符合資料時回傳 HTTP 200 與空 `items`；資料不完整時仍回傳 HTTP 200 並透過 domain status 揭露；無效 filter 回傳 HTTP 422；未宣告的查詢參數（例如打錯的篩選名稱，或只有 series 才接受的 `bucket`）即使值為空也回傳 HTTP 422，訊息列出這些參數；值為空的已宣告篩選視為沒有篩選。未宣告參數的檢查先於 cursor 檢查，因此同時帶錯 cursor 時仍回 422；無效或不相容 cursor 回傳 HTTP 400；`start`、`end` 與時間篩選只接受 RFC 3339 date-time（`YYYY-MM-DDTHH:MM`，秒、至多六位小數與 `Z`／`±HH:MM` offset 可省略，無 offset 視為台北時間），且須落在 1970 至 2199 年之間；`now`、只有日期或年份、以空白分隔、offset 的 `+` 未經 URL 編碼而變成空白等其他寫法一律回 HTTP 422，不由伺服器猜測。任何參數值含控制字元（U+0000–U+001F、U+007F）回 HTTP 422；cursor 內的排序鍵含控制字元、cursor 超過 4096 字元或巢狀過深則回 HTTP 400。時間窗（沒有 cursor 時）與 cursor 的檢查都在任何資料庫讀取之前完成，TimescaleDB 無法連線時這些請求仍回 422／400；`missing_station_id`、`missing_geocode` 逐字比對識別碼，`%`、`_` 不作萬用字元；`all_vintages` 以 `1`、`true`、`yes`、`on`、`t`、`y`（不分大小寫）為開啟，列表與圖表讀法相同；TimescaleDB 無法連線時回傳 HTTP 503。Series endpoints 沿用同一組語意（無資料回 200 與空 `series`，點數超限另帶 `suggested_bucket`），詳見 [rest-api.md](rest-api.md) §5.3。
- **時間範圍上限**：10 分鐘快照與機組資料單次最多查詢 7 天；逐時負載、測站觀測與 audits 最多 31 天；鄉鎮預報有效時間最多 14 天。更長歷史必須移動有界時間視窗取得。Series endpoints 的窗口上限另為 92 天，與列表上限無關；窗口超過列表上限時前端不送 list 請求（§3 時間窗口）。

## 8. 圖表與聚合語意

- **圖表卡片**：有圖表的資料頁在表格上方顯示一張圖表卡片，與表格共用同一個窗口與篩選。粒度（`bucket`）與聚合（`agg`）選單寫入 URL，預設值（`auto`、`avg`）不寫入；這兩個參數不送進 list 請求、不綁進 cursor，因此改圖表設定時 cursor 保留，而改窗口或篩選時 cursor 照常清除、圖表設定保留。Refresh 同時重新取得狀態、圖表與表格。點擊資料點只顯示 tooltip，不跳轉；拖曳框選改變窗口（§6）。URL 中無效或不適用的圖表設定視同預設、不送出：例如未知的粒度（`bucket=5m`）以 `auto` 請求，沒有分組選單的圖忽略 `group_by`，計數圖忽略 `agg`；選單顯示的就是實際請求的設定。明確選「原始」（`raw`）時清除聚合：URL 與 series 請求都不帶 `agg`，停用的聚合選單顯示「平均」，切回 `1h` 或 `1d` 時聚合從「平均」開始；URL 中 `bucket=raw` 旁的 `agg` 也被忽略。「自動」保留選定的聚合，因為伺服器可能把 `auto` 解析成有聚合的粒度。
- **成員合成**：一個分組內同一時間點有多個成員時（例如同一 `unit_type` 下的多部機組），先在該時間點把成員加總成一個值，`NULL` 成員略過，全部成員皆為 `NULL` 時該點為 `null`。逐時負載每個 `subject` 每小時只有一列，沒有成員合成。氣溫、濕度、機率等欄位永不跨成員合成：測站觀測固定依測站分組，鄉鎮預報固定依 `geocode` 分組，避免 GLOSSARY「加權天氣」列為 Avoid 的等權平均。
- **機組發電圖**：預設依 `unit_type` 分組，畫成正負號分開堆疊的面積圖：正值由零軸往上堆疊，儲能負載充電的負值由零軸往下堆疊，各類型沿用集中配色的家族色相。分組選單提供「依類型」與「總和」（`group_by=none`，所有成員的總淨發電量一條），選擇寫入 URL 的 `group_by`，預設的「依類型」不寫入。`unit_type`、`unit_name` 篩選先縮小參與合成的機組。series endpoint 接受 `net_generation_mw` 與 `capacity_mw`，兩者皆為可加總的 MW；主控台不提供欄位選擇，只畫預設的 `net_generation_mw`（見欄位選擇）。百分比欄位 `capacity_ratio_pct` 不跨機組合成，因此 endpoint 不開放。
- **測站觀測圖**：預設每個測站一條 `temperature_c` 線，顏色依測站固定；series endpoint 不接受 `group_by`。series endpoint 另接受相對濕度、氣壓、降水量與風速，主控台不提供欄位選擇，只畫預設的 `temperature_c`（見欄位選擇）；觀測表沒有露點，風向不列入。逐時補值，規則同下方補值規則。
- **鄉鎮預報圖**：時間軸為 `valid_from`，預設每個 `geocode` 一條最新發布版本的 `temperature_c` 線，版本解析與表格相同，只有一處例外：沒有 `dataset_id` 篩選時，兩個預報產品常共用同一個最新 `issued_at`，而 `F-D0047-091` 的更新時間通常晚幾十秒，表格因此預設為 12 小時區間的一週預報；圖表與首頁 sparkline 在共用最新發布時間的版本中優先取逐時的 `F-D0047-089`，避免預設圖變成階梯狀。表格的解析不變，兩者的集中屬 [#102](https://github.com/shiroki9979/shiro-mlops/issues/102)。開啟 `all_vintages` 時必須指定 `geocode`：有 `geocode` 時每個發布版本（`dataset_id`、`issued_at`）一條線，以發布時間命名，最新版本最亮、較舊版本漸暗（超過色階的較舊版本共用最暗的顏色）；同一發布時間有多個更正版本時取 `source_updated_at` 最新者。沒有 `geocode` 時不送 series 請求，圖表位置提示使用者指定 `geocode`，表格照常查詢。預報不補值，只回傳有值的點，線段連接相鄰的點、不畫灰底帶。
- **時間聚合**：`1h` 與 `1d` 在每個 bucket 內對合成後的值取 `avg`、`min` 或 `max`；不提供 `sum`（`agg=sum` 回 422）。`raw` 不做時間聚合並忽略 `agg`。
- **計算順序**：先套用窗口與篩選，再做成員合成，最後做時間聚合；因此邊界 bucket 只用窗口內的資料計算。例：機組 A 為 100..150、B 為 60..0 時，逐點合計為 160, 150, …，`1h` 的 `max` 為 160，而不是各成員最大值相加的 210。
- **Bucket 對齊**：`1h` 對齊整點，`1d` 對齊台北日界（00:00 `+08:00`），bucket 時間標示其起點。TimescaleDB 以 `time_bucket(..., 'Asia/Taipei')` 計算；SQLite 以對應的時間截斷計算，台北無日光節約時間，固定 +8 小時即可精確對齊。只涵蓋到一部分的邊界 bucket 仍保留，前提是該 bucket 至少有一個應到的時段落在窗口內：逐時資料自 10:30 起的窗口沒有 10:00 這個時段，`1h` 的第一個 bucket 為 11:00，不會多出一個 `null` 點；10 分鐘資料自 10:30 起則保留 10:00 的 bucket（含 10:30、10:40、10:50 三個時段）。
- **補值規則**：有固定節奏的資料集由應用層產生窗口內所有預期的 bucket（`raw` 依資料集節奏，自窗口起點後的第一個節奏點起算；`1h`、`1d` 自包含起點的 bucket 起算），沒有資料的 bucket 補 `null`，不使用 TimescaleDB 專屬的 gapfill。尚未到期的 bucket 不算缺口，也不補 `null`：只考慮起點不晚於 `min(end, 現在)` 的 bucket；逐時負載的時間標示其彙總的小時，該小時結束後才到期，與列表缺口一致。前端在 `null` 處斷開線段並加灰底帶。
- **欄位選擇**：只有全台與區域供需的圖表提供欄位多選。其他圖（逐時負載、機組發電、測站觀測、鄉鎮預報與 audits）一律只畫預設欄位，URL 中手寫的 `fields` 全部忽略。提供欄位多選時，所選欄位以 `fields` 寫入 URL（多個欄位時為陣列），與預設欄位相同時不寫入；`fields` 與其他圖表設定一樣不送進 list 請求、不清除 cursor。一張圖最多兩種單位：第一種單位用左軸，第二種用右軸，單位順序依選取順序；已選滿兩種單位時，第三種單位的欄位停用；最後一個已選欄位不能取消。URL 中不在可選欄位內的欄位，以及依選取順序排在第三種單位的欄位，都會被忽略；全部被忽略時畫預設欄位。
- **全台供需圖**：不分組，預設畫目前用電負載（`curr_load_mw`）與即時最大供電能力（`real_hr_maxi_sply_capacity_mw`）兩條線，兩線的距離即供電餘裕；可另選預估、昨日的功率欄位與使用率、備轉容量率等百分比欄位。
- **區域供需圖**：固定依 `region` 分組，四區各一條線，不提供四區合成，以免與全台逐時實際負載的口徑混淆。圖表只帶 `region` 篩選；`completeness` 只篩選表格列（series endpoint 對它回 422：完整度是逐一 10 分鐘時段的判定，`1h`／`1d` bucket 內各時段的完整度可能不同，沒有對應的意義），圖表照常畫出所有時段並以底帶標示不完整處：某個 bucket 四區全部為 `null` 時是缺口（灰底帶），只有部分區域為 `null` 時加琥珀色底帶。比所選粒度更細的不完整（例如 `1h` bucket 內缺了一個 10 分鐘時段）由缺口清單揭露。
- **萬瓩 tooltip**：全台與區域供需的功率欄位，tooltip 同時顯示 MW 與萬瓩（`萬瓩 = MW ÷ 10`，§3 功率單位）；萬瓩由前端換算，API 只回 MW。百分比欄位只顯示一次。
- **點數上限**：每條 series 最多 1,200 點，所有 series 合計最多 10,000 點；`auto` 選出同時符合兩者的最細粒度，手動粒度超限時回 422 並附建議粒度（[rest-api.md](rest-api.md) §5.3）。
- **Audit 狀態時間軸**：CWA 觀測批次與預報版本審計頁的預設圖是依 `status` 堆疊的長條圖，每個 bucket 顯示各狀態的批次數或版本數，顏色取自集中配色的 audit 狀態色，圖例與 tooltip 顯示翻譯後的狀態名稱。這兩頁只有粒度選單、沒有聚合選單，series 請求不帶 `fields` 與 `agg`。計數不做成員合成或時間聚合；`raw` 時每個批次或版本各是一點，同一時間點的版本在圖上相加。audits 不補值，沒有擷取紀錄的 bucket 不畫長條、也不加灰底帶，缺漏的擷取由空白的時段呈現。
- **配色**：類別顏色（四區、12 種 `unit_type`、測站、audit 狀態、預報版本）集中定義在 `frontend/apps/engineering-console/src/lib/chart-palette.ts`，跨頁一致；同家族的機組類型（燃氣與民營電廠-燃氣、燃煤與民營電廠-燃煤、儲能與儲能負載）共用色相、以明度區分。每個顏色與深色卡片背景的對比至少 3:1（WCAG 非文字對比），由前端單元測試檢查。
- **圖表函式庫**：工程主控台以 `recharts` 繪圖，版本範圍與 Forecast View 相同（`^2.15.1`），兩個前端 app 共用同一份依賴解析，不引入第二套圖表函式庫或另一個主版本。
- **可及性**：圖表的標籤、圖例與提示文字一律走 i18n 字典；每張圖帶可及性文字，說明資料集、欄位與序列名稱。
