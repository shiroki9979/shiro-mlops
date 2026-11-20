# ADR-0015：預報檢視在雲端只公開預先算好的預報，地端負責全部運算

> - Created: 2026-11-19
> - Last Updated: 2026-11-20
> - Author: Bo-Xue Huang
> - Status: 已接受
> - Supersedes: [ADR-0001](0001-hybrid-topology-boundary.md)
> - Related: [ADR-0004](0004-dagster-asset-based-orchestration.md)、[ADR-0006](0006-timescaledb-local-storage-layer.md)、[ADR-0007](0007-isolate-cwa-access-behind-scheduled-ingestion.md)、[ADR-0013](0013-present-forecast-track-record-from-scheduled-issued-forecasts.md)、[ADR-0014](0014-keep-engineering-console-local-and-split-frontend-apps.md)、[GLOSSARY.md](../../GLOSSARY.md)

---

## 1. Context

M4 要以單一 AWS 展示環境、每月 10 美元以內、AWS 預設網址公開預報檢視（[GitHub #123](https://github.com/shiroki9979/shiro-mlops/issues/123)）。地端工作站 24/7 運行，展示資料允許延遲數小時至一天。

[ADR-0001](0001-hybrid-topology-boundary.md) 規定雲端以 App Runner 或 ECS Fargate 託管 FastAPI 隨需推論，S3 則作為集中式 Data Lake、Feast Registry 與 MLflow artifacts 儲存。這些規定與現況不符：

- **serving 只讀地端資料**：serving 只讀地端 TimescaleDB 的 canonical tables（[ADR-0006](0006-timescaledb-local-storage-layer.md)／[ADR-0007](0007-isolate-cwa-access-behind-scheduled-ingestion.md)），模型也從地端檔案系統的模型目錄載入，現有 API 無法直接搬上雲。
- **託管選項已不可行**：App Runner 自 2026-04-30 起不再開放新客戶；Fargate 常駐即超出預算（[GitHub #125](https://github.com/shiroki9979/shiro-mlops/issues/125)）。
- **S3 的雲端角色從未啟用**：地端一直以 `ENVIRONMENT=local` 運行，`ENVIRONMENT=aws` 的 S3 I/O 分支從未在營運中使用。
- **`as_of` 不能用「現在」**：雲端若以「現在」為 `as_of`，會把資料搬運的延遲誤報為負載起點過舊或降級預報。任何做法都必須以發布或快照的時點為準（[GitHub #124](https://github.com/shiroki9979/shiro-mlops/issues/124)）。

[ADR-0013](0013-present-forecast-track-record-from-scheduled-issued-forecasts.md) 已決定地端每小時發布 $H = 168$ 的已發布預報，並在地端計算預報實績；[ADR-0014](0014-keep-engineering-console-local-and-split-frontend-apps.md) 已決定工程主控台只留地端。剩下要決定的是：預報檢視在雲端是否提供隨需推論，以及地端與雲端的權責邊界。

## 2. Decision

### 2.1 服務形態

雲端**只公開預先算好的預報**，不跑任何推論或運算：

- `/` 顯示**最新一份已發布預報**，`/history` 顯示預報實績，兩者同源。
- 預報時刻（定義見 GLOSSARY.md）即已發布預報的發布時刻，對應 `as_of`。雲端不以觀眾開頁的當下重新判定運行狀態或負載起點過舊。
- 隨需 `/predict` 只留在地端，供工程主控台的測試推論使用。

### 2.2 權責邊界

- **地端**：資料擷取、特徵、訓練、隨需推論、已發布預報、預報實績、Feast、Dagster I/O、MLflow 與工程主控台。已發布預報的永久紀錄依 ADR-0013 只存在地端。
- **雲端**：只存放並提供預報檢視的發布產物，包括前端建置產物、最新已發布預報與預報實績的 JSON。雲端不是 Data Lake，也不是地端資料的備份。
- **雲端元件**：
  - S3 bucket（發布產物）與 CloudFront（origin、behavior 與快取細節由 [GitHub #128](https://github.com/shiroki9979/shiro-mlops/issues/128) 決定）。
  - GitHub OIDC provider 與 CI 角色（Terraform state 與 apply 權責由 [GitHub #129](https://github.com/shiroki9979/shiro-mlops/issues/129) 決定）。
  - 地端上傳用 IAM 使用者與 AWS Budgets。
  - 區域為 `ap-northeast-1`。
- **移除**：
  - API 與 Dagster 的 ECR repository、App Runner instance role 及其 S3 policy attachment。
  - `ENVIRONMENT` 的 `aws` 值，以及它所切換的 S3 I/O 與特徵 Parquet 分支。

### 2.3 地端到雲端的匯出

- **Dagster 資產**：匯出是 Dagster 資產，位於已發布預報與預報實績之後，每小時隨發布執行。失敗時在地端 Dagster 執行紀錄可見，與其他資產在同一張血緣圖（[ADR-0004](0004-dagster-asset-based-orchestration.md)）。
- **先寫地端，再上傳**：匯出一律先寫入地端目錄；有設定 S3 時，再把同樣的檔案上傳到 bucket 的資料 prefix。沒有 AWS 憑證時，地端展示照常運作。
- **憑證**：地端使用專用 IAM 使用者的長期 access key，放在地端 `.env`，手動輪替。權限只允許寫入資料 prefix，不能刪除，也不能讀寫其他 prefix。key 外洩時，最多能竄改公開展示的兩份 JSON，可由舊版本復原（§2.6）。前端產物由 CI 經 OIDC 上傳，與地端 key 的權限互不重疊。

### 2.4 公開資料契約

- **單一契約**：預報檢視只讀匯出的 JSON，以相對路徑 `/published/` 取得，不呼叫任何 API。地端 Nginx 提供地端目錄，雲端由 CloudFront 提供 S3，兩邊的行為相同。路徑前綴不用 `/data/`，以免與 ADR-0014 的工程主控台路徑檢查衝突。
- **最新已發布預報**：只公開預報時刻、目標小時與預測負載，而且只含目標小時晚於預報時刻的步。運行狀態、負載起點、天氣值、天氣來源與模型版本都不公開。
  - 降級預報的天氣值可能來自測站觀測或歷史平均；不揭露運行狀態卻標示為預報天氣，會誤導觀眾。
- **預報實績**：沿用 ADR-0013 §2.3 的公開欄位，另加**統計截至時刻**。
- **具體格式**：JSON 的具體格式於實作工單記錄在 SPEC。

### 2.5 預報檢視的呈現

- **視界選擇**：保留視界預設按鈕，由前端從最新已發布預報截取，截取的起點是預報時刻，不是觀眾開頁的當下。「一週」顯示的是該份預報實際涵蓋的全部未來小時，負載起點落後 $k$ 小時時為 $168 - k$ 小時。
- **過舊提示**：預報時刻或統計截至時刻距觀眾當下超過 24 小時時，顯示一行中性提示，例如「預報已超過 24 小時未更新」。提示不揭露原因（地端斷線、匯出失敗或負載起點過舊皆屬系統狀態），舊內容照常顯示。
- **空狀態**：還沒有任何已發布預報時，`/` 顯示空狀態；`/history` 的空狀態沿用 ADR-0013 的 7 天規則。

### 2.6 保存規則與護欄

- **雲端只放最新一份**：匯出每次覆寫固定的檔名，雲端不做歷史封存。
- **versioning 保留**：舊版本 30 天後過期，用於復原被竄改或錯誤的匯出；前端產物適用同一規則。
- **成本護欄**：AWS Budgets 在月實際支出達 5 美元、預測支出達 10 美元時寄 email 警示。
- **雲端不開 log**：CloudFront 標準 log 與 CloudWatch 都不開。預報新舊已由公開的時刻揭露，匯出失敗則在地端可見。

### Rationale & Alternatives Considered

- **選定方案：只公開預先算好的預報**。ADR-0013 已產出 `/` 所需的已發布預報，兩頁同源，數字都是系統在營運中真正說過的話。雲端沒有運算，月費約 0 美元；地端不開對外入口，地端斷線時仍能顯示最後一版。`as_of` 語意由發布時刻自然保留，不必在雲端重建降級與負載起點過舊的判定。
- **候選方案 A：公開隨需推論**（Lambda 容器映像 + Function URL，經 CloudFront OAC，讀 S3 快照）。
  - 需要精簡的 serving 映像（全量相依匯入約 4.4 秒，逼近 Lambda Init 10 秒上限）、速率限制與濫用防護、repository Protocol 與從 S3 載入模型，並修訂 ADR-0007。
  - `/` 的隨需預報與 `/history` 的已發布預報來源不同。月費約 0.1–0.5 美元。
- **候選方案 B：預先算好的預報為主，另加隨需推論**。可共用同一條 S3 匯出管線，但兼具 A 的全部成本；列為日後方向，不在 M4 範圍。
- **候選方案 C：雲端經通道連回地端資料庫，或地端 API 經通道對外**。中繼最低約每月 8.4 美元，VPN 為 35–146 美元，超出預算；而且會暴露地端，地端斷線時預報檢視完全沒有資料。
- **候選方案 D：保留 S3 作為 Data Lake、Feast offline 層或 MLflow artifacts**。這些角色從未啟用；保留只會讓雲端承擔與公開展示無關的責任，ADR 也名不副實。地端備份若有需要，另行決策。
- **候選方案 E：以 IAM Roles Anywhere 取代長期 access key**。不需長期 key，但要自建 CA 並管理憑證到期；key 外洩的影響已限縮為可復原的公開資料竄改，延後。
- **候選方案 F：地端預報檢視改由 API 提供相同契約**。同一份契約要有兩種傳輸實作，預報檢視也仍依賴 FastAPI。
- **候選方案 G：公開運行狀態與天氣值**。可以解釋負載高低，但與 ADR-0013 `/history` 不揭露運行狀態的規則不一致，也違反 GLOSSARY 中預報檢視不揭露資料缺口的定義。
- **候選方案 H：預報過舊時改為空狀態**。觀眾看不到系統最後說了什麼；舊預報加上預報時刻與提示已足以讓觀眾判斷。
- **候選方案 I：視界以觀眾開頁當下截取**。同一份已發布預報會因開頁時間不同而內容不同，與「顯示已發布預報」的語意不合。

## 3. Consequences

- **正面效益（Positive）**：
  - 雲端月費約 0 美元，沒有冷啟動、映像大小與速率限制的問題，地端不開對外入口。
  - 預報檢視與 FastAPI 沒有相依，地端與雲端行為相同；沒有 AWS 憑證時地端仍可完整展示。
  - 公開欄位在 `/` 與 `/history` 適用同一套揭露規則。
  - CD 管線只需建置並上傳 `forecast-view`，不需映像發布。
- **代價與風險（Trade-offs & Risks）**：
  - 作品中沒有雲端推論 API；雲端工程的練習集中在 Terraform、CloudFront、OIDC CD 與成本護欄。
  - 觀眾無法取得比最新已發布預報更新的預報，資料最多落後約一小時加上匯出時間。
  - 地端工作站保存一把長期 access key，需要手動輪替。
  - 公開頁面不再呈現天氣曲線，負載高低少了直觀的解釋。
  - `ENVIRONMENT=aws` 與 S3 I/O 分支的移除會動到 Dagster 定義與設定。
- **不做／延後範圍（Out of Scope / Deferred）**：
  - 雲端隨需推論（候選方案 B）。屆時須以新 ADR 加回 serving 映像、速率限制，以及 ADR-0014 §2.1 的雲端防護。
  - CloudFront 配置（#128）、Terraform state 與 apply 權責（#129）、CD 管線的具體步驟。
  - IAM Roles Anywhere、地端資料的雲端備份、自訂網域。

## 4. Compliance

- **匯出資產測試**：沒有 S3 設定時只寫地端目錄；輸出不含運行狀態、負載起點、天氣值、天氣來源與模型版本；最新已發布預報只含目標小時晚於預報時刻的步；預報實績含統計截至時刻。
- **前端測試**：預報檢視不呼叫任何 API；視界從預報時刻截取；時刻超過 24 小時時顯示提示；沒有已發布預報時顯示空狀態。
- **Terraform 審查**：沒有 ECR、App Runner 與運算資源；地端 IAM 使用者只能寫入資料 prefix，沒有刪除權限；bucket 有 30 天舊版本過期規則；有 Budgets 警示。
- **部署後 smoke check**：首頁與兩份 JSON 回應 200，且預報時刻不超過 24 小時。
- **Code Review 清單**：雲端不得新增運算資源或讀取地端資料庫的通道；預報檢視不得重新加入 API 呼叫；`as_of` 不得以觀眾當下重新計算。

## 5. Notes

- 決策經 2026-11-19 的設計訪談定案（[GitHub #127](https://github.com/shiroki9979/shiro-mlops/issues/127)，地圖 [#123](https://github.com/shiroki9979/shiro-mlops/issues/123)）。成本與可行性取自 #124、#125 的研究報告；其中 AWS 文件類事實為搜尋摘錄，實作前應開原頁複核。
- 本 ADR 取代 ADR-0001。修訂了 ADR-0013 §2.3 的公開欄位（加入統計截至時刻），也使 ADR-0006 的 S3 Gold／Feast offline 層與 ADR-0014 §2.1 的雲端 FastAPI 前提不再成立；各 ADR 的 Notes 已記錄。ADR-0007 不受影響。
- 實作追蹤：[ROADMAP M4](../ROADMAP.md) TICKET-405（修訂）、TICKET-408–411；TICKET-407 不再需要。
- 2026-11-20：§2.2 交由 [GitHub #128](https://github.com/shiroki9979/shiro-mlops/issues/128) 的 CloudFront 配置已定案，記錄於 [預報檢視託管規格](../reference/forecast-view-hosting.md)，未另開 ADR（設定可隨時調整，不符合難以逆轉的條件）。重點：同一 bucket 分 `site/` 與 `published/` 兩個 prefix，CI 與地端 key 各寫一個；SPA fallback 用只掛在預設 behavior 的 CloudFront Function，不用 custom error response，讓 `/published/` 缺檔照實回錯誤；快取由 CloudFront 依 behavior 決定，部署不做 invalidation；採隨用隨付與 `PriceClass_200`，固定費率 Free 方案因前提未證實而延後，重新評估條件見 SPEC §8.6。實作追蹤：TICKET-412，並修訂 TICKET-405、408–410。
