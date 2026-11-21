# 預報檢視的雲端託管

- 建立日期：2026-11-20
- 最後更新：2026-11-21
- 專案版本：`0.4.0`

> 由 `docs/SPEC.md` 第 8 節拆出。

---

依 [ADR-0015](../adr/0015-publish-forecast-view-as-static-precomputed-output.md)，雲端只以 S3 + CloudFront 提供預報檢視的發布產物，沒有 API origin。本節的配置經 [GitHub #128](https://github.com/shiroki9979/shiro-mlops/issues/128) 定案，由 TICKET-412 實作。

## 1. S3 配置與寫入權限

單一 bucket，名稱由 Terraform 變數 `s3_bucket_name` 傳入，部署後以 `terraform output -raw s3_bucket_name` 取得；維持 public access block，只經 CloudFront Origin Access Control（OAC）讀取，不使用 S3 website endpoint。

| prefix | 內容 | 寫入者 |
| :--- | :--- | :--- |
| `site/` | `forecast-view` 建置產物（`index.html`、`assets/*` 等） | CI 角色（GitHub OIDC），只能寫 `site/*` |
| `published/` | 匯出的兩份公開 JSON（[資料契約 §6](data-contracts.md#6-預報檢視公開-jsonpublished)） | 地端上傳用 IAM 使用者，只能 `PutObject` 到 `published/*` |

bucket policy 只授權 CloudFront 服務主體經該 distribution 的 `s3:GetObject`，不授權 `s3:ListBucket`；不存在的物件因此回 403 而非 404，前端不依狀態碼區分缺檔原因（§4）。

地端匯出資產 `forecast_view_export`（[Dagster 排程](dagster-schedules.md)第 8 項）讀取下列設定項目。值只放在地端 `.env`，由 Compose 傳入 `dagster-webserver` 容器，不提交到 repo；`.env.example` 只列名稱與區域預設值。

| 設定 | 用途 | 未設定時 |
| :--- | :--- | :--- |
| `FORECAST_VIEW_S3_BUCKET` | 上傳目標 bucket，填 Terraform 輸出 `s3_bucket_name` 的值；key 固定為 `published/<檔名>` | 只寫地端目錄 `DATA_DIR/published/`，不建立 S3 client |
| `AWS_DEFAULT_REGION` | bucket 所在區域，須等於 Terraform 輸出 `aws_region`（來自變數 `aws_region`） | `ap-northeast-1`，即該變數的預設值 |
| `AWS_ACCESS_KEY_ID` | 地端上傳用 IAM 使用者的 access key ID | 交給 boto3 的預設憑證鏈；找不到憑證時上傳失敗 |
| `AWS_SECRET_ACCESS_KEY` | 同一把 key 的 secret；設定物件以 `SecretStr` 保存，不出現在其 repr | 同上 |

- 區域由 Terraform 變數 `aws_region` 決定，地端以 `AWS_DEFAULT_REGION` 對齊；prefix 固定為 `published/`，不開放設定，以免與 IAM policy 及 CloudFront behavior 脫鉤。
- key 為長期 access key，手動輪替（ADR-0015 §2.3）；任一設定變更後更新 `.env`，再以 `docker compose --env-file .env -f docker/docker-compose.yml up -d --force-recreate dagster-webserver` 重建容器。單純重新啟動（`restart`）不會重新讀取 `.env`，容器仍沿用舊值。

## 2. Origin 與 behavior

同一 bucket 開兩個 origin：`site`（origin path `/site`）與 `published`（無 origin path）。

| behavior | origin | CloudFront Function | 邊緣快取 | 瀏覽器 `Cache-Control` |
| :--- | :--- | :--- | :--- | :--- |
| 預設（`*`） | `site` | `spa-rewrite`（viewer-request） | 不快取（TTL 0） | `no-cache` |
| `/assets/*` | `site` | 無 | 長期 | `public, max-age=31536000, immutable` |
| `/published/*` | `published` | 無 | 60 秒 | `public, max-age=60` |

- **快取規則集中在 CloudFront**：TTL 由 cache policy 決定，瀏覽器標頭由 response headers policy 覆寫；上傳端（CI 與地端匯出）不設定物件的 `Cache-Control` metadata。
- **地端對應**：地端 Nginx 的 `/assets/`、`/index.html` 沿用既有標頭，`/published/` 同樣回 `public, max-age=60`。Compose 把主機的 `data/published/`（即 Dagster 的 `DATA_DIR/published/`）唯讀掛載到 frontend 容器的 `/usr/share/nginx/published`，`/published/` 以 `try_files $uri =404` 提供，缺檔回 404，不落到 SPA fallback；目錄本身不列出檔案。掛載整個目錄而非單檔，因為匯出以 rename 替換檔案，單檔 bind mount 會一直指向舊檔。
- **SPA fallback**：`spa-rewrite` 把最後一段沒有副檔名的路徑（含 `/`、`/history`、`/history/`）內部改寫為 `/index.html`，等價於地端 Nginx 的 `try_files $uri $uri/ /index.html`。不使用 custom error response，因其作用於整個 distribution，會讓 `/published/` 下的缺檔回 200 與 HTML。`/api/*`、`/console/*` 不特別處理，落到預報檢視的 not-found 頁。
- **原始碼與測試**：`infra/terraform/functions/spa-rewrite.js` 由 Terraform `file()` 讀入；同目錄以 `node --test` 撰寫離線測試，涵蓋 `/`、`/history`、`/history/`、`/assets/x.js`、`/favicon.ico`、`/console/foo`，於 CI 執行。

## 3. Distribution 其他設定

| 項目 | 設定 |
| :--- | :--- |
| 計費 | 隨用隨付（不訂閱固定費率方案，見 §6） |
| Price class | `PriceClass_200`（`PriceClass_100` 不含台灣與日本的邊緣節點） |
| 網址與憑證 | AWS 預設 `*.cloudfront.net` 與其預設憑證 |
| Viewer protocol | `redirect-to-https` |
| 壓縮 | gzip 與 Brotli |
| HTTP 版本 | HTTP/2 與 HTTP/3 |
| 安全標頭 | AWS 托管 `SecurityHeadersPolicy`；不自訂 CSP；地端 Nginx 不跟進 |
| WAF、地理限制、標準 log | 皆不設（log 依 ADR-0015 §2.6） |

## 4. 前端讀取 `/published/`

- 預報檢視以相對路徑 `/published/` 讀取 JSON，沒有 API base URL 設定；`VITE_API_BASE_URL` 只供工程主控台使用。
- 非 2xx、網路錯誤、JSON 解析失敗或內容不符[資料契約 §6](data-contracts.md#6-預報檢視公開-jsonpublished)（以 zod schema 驗證，未知的多餘欄位忽略）一律顯示中性的錯誤狀態（例如「目前無法取得預報」），不區分原因；空狀態只由匯出 JSON 的內容決定，不由 HTTP 狀態碼推斷。
- `/history` 的預報實績在背景每 5 分鐘重新讀取一次，失敗不自動重試，由下一次背景讀取恢復；已有資料時背景讀取失敗，保留畫面上的內容，不切換到錯誤狀態。
- 過舊提示：JSON 內帶 offset 的時刻（`/history` 為統計截至時刻）換算成絕對時間後，距觀眾的 `Date.now()` 嚴格超過 24 小時才顯示一行中性提示，剛好 24 小時不顯示，不揭露原因，內容照常顯示；每次 render 時判斷，不另設計時器，錯誤狀態不顯示。
- `pnpm dev` 時，預報檢視的 Vite dev server 以 proxy 把 `/published` 原樣（不改寫路徑）轉送到地端 Compose 的 Nginx（`http://localhost:8080`）；Vitest 以 MSW 攔截 `/published/` 請求。

## 5. 部署與驗證

- **上傳順序**：先上傳 `site/assets/*`，再上傳 `site/index.html`；舊 assets 以 `sync --delete` 立即刪除，被刪物件依 ADR-0015 §2.6 的版本規則 30 天後過期。
- **不做 invalidation**：`index.html` 邊緣不快取、assets 帶 hash，部署後不需 CloudFront invalidation。
- **雲端 smoke check**：除 ADR-0015 §4 的項目（首頁與兩份 JSON 回 200、預報時刻不超過 24 小時）外，另驗證：
  - `/history` 回 200 且為 HTML；
  - `/published/` 下不存在的檔案不回 200。
- CD 管線的其餘步驟待 [GitHub #129](https://github.com/shiroki9979/shiro-mlops/issues/129)（Terraform state 與 apply 權責）定案。

## 6. 固定費率方案的重新評估條件

CloudFront 固定費率 Free 方案（每月 0 美元、超量不收費而改為調整傳遞）可為月費設硬性上限，但 M4 不採用。日後重新評估前須以 AWS 原頁確認下列前提（#128 的研究只取得搜尋摘錄）：

- 只用 `*.cloudfront.net`、不掛自訂網域的 distribution 可以訂閱。
- 帳號為付費帳號方案（Free 帳號方案不可訂閱）。
- Terraform AWS provider 升級至 ≥ 6.69（`aws_pricingplanmanager_subscription`），現行為 `~> 5.0`。
- 每個訂閱必須綁定一個 WAF web ACL，distribution 須使用 cache policy；訂閱期間無法刪除 distribution，`terraform destroy` 須先移除訂閱。
- 方案不能設定 price class，邊緣節點由 AWS 決定。
