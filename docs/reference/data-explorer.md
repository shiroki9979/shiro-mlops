# 營運資料檢視器 (Data Explorer)

- 建立日期：2026-11-20
- 最後更新：2026-11-21
- 專案版本：`0.4.0`

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
- **時間窗口**：列表與完整度查詢共用精確閉區間 `[start, end]`；兩端點納入、窗口外一微秒排除，`start = end` 合法。cursor 固定第一次解析的窗口，頁面顯示時間維持既有整秒格式。
- **歷史可達性**：使用者可透過有界時間範圍與 cursor 逐頁檢視所有保留中的歷史資料。
- **時間呈現**：API 回傳帶 `+08:00` offset 的 RFC 3339 timestamp；介面明示時區為 `Asia/Taipei`。
- **功率單位**：介面以 MW 為主要顯示單位；對於以萬瓩儲存的全台與區域供需 typed values，在明細或 tooltip 同時顯示儲存值，並依 `1 萬瓩 = 10 MW` 轉換。
- **預報版本**：CWA 鄉鎮預報預設顯示最新發布版本；可以 `dataset_id`、`issued_at`、`source_updated_at` 與 `geocode` 篩選所有已保存 forecast vintages。v1 不另建 Effective Serving View。

## 4. 營運狀態語意

- **新鮮度**：每個 dataset 依自身預期更新頻率判定；超過兩個預期更新週期未取得新資料時顯示 warning。CWA forecast ingestion 新鮮度與 serving 使用的七小時 stale 規則必須分開顯示，不得混為同一狀態。
- **全台供需完整度**：每個 observation slot 預期一筆資料。
- **區域供需完整度**：每個 observation slot 預期同時具備北、中、南、東四區；缺少任一區即標記該 slot 不完整。列表的 `missing_slots` 以整個查詢窗口計算：窗口內每個預期的 10 分鐘時段只要不足四區（包含四區全缺、沒有任何資料列的時段）即列為缺口，結果不隨分頁或 `region`／`completeness` 篩選變動，口徑與逐時負載、全台供需、測站觀測一致。`GET /data/status` 仍只判定最新一個 slot 缺少的區域。
- **列表缺口範圍**：`missing_slots` 只檢查已發生的預期時段，即 `min(end, 現在)` 之前；窗口延伸到未來時，尚未到來的時段不列為缺口。逐時負載只檢查到最近一個已完成的小時。各列表的 `missing_slots` 以時間遞增排列。
- **CWA 完整度**：以 allowlist 與 observation batch／forecast release audit header 判定缺少的測站或行政區。
- **逐時負載完整度**：在查詢時間區間內檢查預期的逐小時時間點，並揭露缺口。
- **機組完整度**：機組數量可變，不以固定筆數判定失敗。
- **空值語意**：資料契約允許的 nullable 欄位不得僅因為值為 `NULL` 就標記 dataset 不完整。

## 5. 介面與 API 邊界

- **前端路由**：在 `/console/` 之下提供 `/data/power/load`、`/data/power/supply-demand`、`/data/power/regional`、`/data/power/units`、`/data/weather/observations`、`/data/weather/forecasts` 與 `/data/audits` nested routes，支援重新整理與 deep link。側邊欄在 Data Explorer 啟用時列出上述資料集與 CWA audits。`GET /data/status` 回傳的 `href` 是不含 base path 的工程主控台路由（如 `/data/power/load`），前端產生連結時補上 `/console`。
- **資料 API**：每個領域 dataset 使用獨立 typed read endpoint：`GET /data/power/load`、`GET /data/power/supply-demand`、`GET /data/power/regional`、`GET /data/power/units`、`GET /data/weather/observations`、`GET /data/weather/forecasts`、`GET /data/audits/cwa-observations` 與 `GET /data/audits/cwa-forecasts`。所有 list endpoints 共用 cursor pagination response envelope；不提供任意 SQL 或任意實體資料表查詢。
- **Audit 呈現**：CWA observation 與 forecast 資料頁顯示最新 audit 狀態及 Audit History 連結；`/data/audits` 提供批次歷史與 missing identifiers，但不提供完整 `raw_payload`。

## 6. 交互與診斷行為

- **Freshness 維度**：分別顯示 ingestion age 與 source age。前者表示距上次成功入庫所經時間，後者表示最新來源事件或發布時間距今時間；不得以其中一者取代另一者。
- **資料表與明細**：列表只顯示核心營運欄位；點擊資料列後以 drawer 顯示該筆所有 typed fields。Data Explorer 表格採緊湊列距（列高約為共用表格預設的 60%），表格區塊高度受限並於內部捲動，表頭固定在上方；緊湊列距與固定表頭只套用於 Data Explorer，共用表格元件預設值與 Forecast View 表格外觀不變。數值欄靠右對齊並使用 tabular-nums；等寬字體只用於數值與識別碼（測站編號、geocode、鄉鎮代碼），時間與文字欄位使用一般字體；單位只寫在欄標題。`slot_complete` 與 audit `status` 以沿用資料集狀態配色的徽章呈現（完整為綠、不完整為琥珀），`region`、`unit_type`、`dataset_id` 以中性 chip 呈現；徽章與 chip 內文與明細 drawer 相同。相鄰兩列首欄時間的台北日期不同時，中間插入日期分隔列（標示下方資料列的日期）；分隔列不可點選，不影響明細 drawer 與 CSV 匯出內容。
- **缺口清單**：有缺口時，列表上方顯示缺口時段數，展開後列出缺口區間。連續缺口依資料集節奏合併：逐時負載與測站觀測為 1 小時，全台與區域供需為 10 分鐘。每個區間標示起訖時段與長度（缺口時段數 × 節奏，如「11/20 03:00–05:00（3 小時）」）；測站觀測依測站編號分組。清單只供閱讀，點擊不改變窗口。
- **篩選條件**：所有 datasets 皆提供時間區間篩選；逐時負載另提供預測對象（`subject`，如 `nationwide`），區域供需提供 region 與完整度，機組發電提供 unit type 與 unit name，測站觀測提供 station，鄉鎮預報提供有效時間、dataset、geocode 與發布／更新版本，audits 提供 audit type、status 與 missing identifier。
  - **值集合固定的欄位**：`region`（北部、中部、南部、東部）、區域供需 `completeness` 與 audit `status`（`complete`、`incomplete`）使用下拉選單，第一個選項「不篩選」清除該篩選；選項以 API 原始值寫入 URL，`completeness` 與 `status` 的顯示文字隨介面語系。`all_vintages` 使用開關，開啟時寫入 `all_vintages=true`，關閉時自 URL 移除。
  - **值集合開放的欄位**：`subject`、`unit_type`、`unit_name`、`station_id`、`geocode`、`dataset_id`、`issued_at`、`source_updated_at` 與 `missing_*` 維持文字輸入；不提供列出 distinct 值的 endpoint。
- **預設窗口與 cursor 失效**：URL 未指定 `start`／`end` 時，前端以進入頁面當下計算預設窗口，同一次瀏覽內不隨重新繪製漂移，且不主動寫入 URL。變更窗口或任一篩選即清除 cursor 並回到第一頁；只有翻頁操作會設定 cursor。
  - **快速區間**：以點擊當下（取整秒）計算。過去方向的 datasets 提供「今天」（台北日 00:00:00 至 23:59:59）、「近 24 小時」、「近 7 天」與「明細上限」（結束於當下，長度為該資料集 list 的時間範圍上限：7、14 或 31 天，見 §7）。鄉鎮預報以有效時間為準、由現在往後，提供「未來 24 小時」、「未來 72 小時」、「未來 7 天」與「未來 14 天」；預設窗口維持「進入當下前 1 小時至後 72 小時」，保留正在生效的預報時段。
  - **平移**：窗口長度 L 為終點減起點再加 1 秒。`‹` 的新窗口為「起點減 L」至「起點減 1 秒」，`›` 的新窗口為「終點加 1 秒」至「終點加 L」；新窗口與原窗口相鄰且不重疊，例如「今天」按一次 `‹` 即為完整的昨天。
  - **URL 更新**：快速區間與平移一次寫入 `start`／`end`（帶 `+08:00` 的 RFC 3339）並清除 cursor，與其他窗口變更走同一條路徑；起訖時間的精確輸入維持原本行為，逐端更新。
- **排序**：v1 固定以最新資料優先，不提供任意欄位的 server-side 排序。
- **更新**：Data Explorer 僅提供手動 Refresh 與最後取得時間；不自動改動正在檢視的歷史頁面或已展開明細。
- **CSV 匯出**：前端可將當前已載入頁面匯出為 CSV；不提供跨頁或無上限的 server-side export。
- **Monitoring 調整**：Monitoring 以 Data Source Status 摘要顯示 availability、freshness 與 completeness，並連結至 Data Explorer 對應資料集；不再提供 Feature Store Snapshot。

## 7. 狀態、存取與失敗契約

- **Data Explorer 首頁**：`/data` 顯示全部 datasets 的最新來源時間、最新入庫時間、freshness、completeness 與明細連結。
- **狀態 API**：`GET /data/status` 是 Monitoring、Data Explorer 首頁與各資料頁的共用狀態來源。Typed list endpoints 不重複計算狀態，並共用含 `items`、`next_cursor` 與 `has_more` 的 pagination envelope。
- **狀態模型**：每個 dataset 分別回傳 `availability` (`available | empty | unavailable`)、`freshness` (`fresh | warning | unknown`)、`completeness` (`complete | incomplete | unknown`) 與衍生的 `overall` (`healthy | warning | critical | unknown`)。`unavailable` 對應 `critical`；`warning` freshness、`incomplete` 或 `empty` 對應 `warning`。
- **Cursor 契約**：八個列表只接受 v2 cursor。cursor 為 opaque、stateless 且與當前窗口及 filters 綁定的 keyset cursor，含最後一筆完整原始排序鍵與契約版本，不設時間期限。更改 filters、v1 或格式無效時回傳 HTTP 400。帶 cursor 的請求收到 400 時，前端顯示返回第一頁的恢復操作（字典鍵 `explorer.results.backToFirstPage`，顯示文字隨介面語系）；使用者點擊後清除 cursor，保留窗口與篩選。明確預報版本保留，隱含最新版本重新解析；422／503 不提供此恢復操作。
- **開啟條件**：v1 不建立應用層登入與 RBAC。Data Explorer 路由與 API 僅在 local environment 或明確啟用功能旗標時可用；非本機存取必須由內網或 reverse proxy 限制，並使用 same-origin CORS，不得依賴現有 `CORS *` 對外暴露。
- **顯示範圍**：目前提供狀態、資料表、篩選、typed detail drawer 與當頁 CSV 匯出。趨勢圖與資料集內可設定欄位、分組、粒度與聚合的探索視覺化規劃於 M9（[GitHub #212](https://github.com/shiroki9979/shiro-mlops/issues/212)），實作時於同一 PR 更新本節。
- **HTTP 語意**：無符合資料時回傳 HTTP 200 與空 `items`；資料不完整時仍回傳 HTTP 200 並透過 domain status 揭露；無效 filter 回傳 HTTP 422；無效或不相容 cursor 回傳 HTTP 400；TimescaleDB 無法連線時回傳 HTTP 503。
- **時間範圍上限**：10 分鐘快照與機組資料單次最多查詢 7 天；逐時負載、測站觀測與 audits 最多 31 天；鄉鎮預報有效時間最多 14 天。更長歷史必須移動有界時間視窗取得。
