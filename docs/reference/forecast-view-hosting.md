# 預報檢視的雲端託管

- 建立日期：2026-11-20
- 最後更新：2026-11-24
- 專案版本：`0.4.0`

> 由 `docs/SPEC.md` 第 8 節拆出。

---

依 [ADR-0015](../adr/0015-publish-forecast-view-as-static-precomputed-output.md)，雲端只以 S3 + CloudFront 提供預報檢視的發布產物，沒有 API origin。本節的配置經 [GitHub #128](https://github.com/shiroki9979/shiro-mlops/issues/128) 定案，已由 TICKET-412 實作於 `infra/terraform/`；瀏覽器 `Cache-Control` 與安全標頭已由 [GitHub #169](https://github.com/shiroki9979/shiro-mlops/issues/169) 實作。

## 1. S3 配置與寫入權限

單一 bucket，名稱由 Terraform 變數 `s3_bucket_name` 傳入，部署後以 `terraform output -raw s3_bucket_name` 取得；維持 public access block，只經 CloudFront Origin Access Control（OAC）讀取，不使用 S3 website endpoint。

| prefix | 內容 | 寫入者 |
| :--- | :--- | :--- |
| `site/` | `forecast-view` 建置產物（`index.html`、`assets/*` 等） | 網站上傳角色 `shiro-mlops-site-deploy`（GitHub OIDC，只信任 `main` 分支 push 的 token），只能列出、寫入與刪除 `site/*` |
| `published/` | 匯出的兩份公開 JSON（[資料契約 §6](data-contracts.md#6-預報檢視公開-jsonpublished)） | 地端上傳用 IAM 使用者，只能 `PutObject` 到 `published/*` |

bucket policy 只有一個 statement：授權 CloudFront 服務主體經該 distribution（條件 `AWS:SourceArn`）對 `site/*` 與 `published/*` 執行 `s3:GetObject`，不授權 `s3:ListBucket`。S3 在呼叫者沒有 `s3:ListBucket` 時對不存在的物件回 403 而非 404，前端不依狀態碼區分缺檔原因（§4）。這個 policy 只授權固定的服務主體與 `AWS:SourceArn`，S3 不視為公開 policy，public access block 因此不需放寬。

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
| 預設（`*`） | `site` | `spa-rewrite`（viewer-request） | 不快取（default TTL 0，見 §3 壓縮） | `no-cache` |
| `/assets/*` | `site` | 無 | 長期 | `public, max-age=31536000, immutable` |
| `/published/*` | `published` | 無 | 60 秒 | `public, max-age=60` |

- **快取規則集中在 CloudFront**：邊緣 TTL 由各 behavior 的 cache policy 決定；瀏覽器 `Cache-Control` 由各 behavior 專用的自訂 response headers policy 以 override 寫入上表的值，同一 policy 也帶 §3 的安全標頭。上傳端（CI 與地端匯出）不設定物件的 `Cache-Control` metadata。
- **地端對應**：地端 Nginx 的 `/assets/`、`/index.html` 沿用既有標頭，`/published/` 同樣回 `public, max-age=60`。Compose 把主機的 `data/published/`（即 Dagster 的 `DATA_DIR/published/`）唯讀掛載到 frontend 容器的 `/usr/share/nginx/published`，`/published/` 以 `try_files $uri =404` 提供，缺檔回 404，不落到 SPA fallback；目錄本身不列出檔案。掛載整個目錄而非單檔，因為匯出以 rename 替換檔案，單檔 bind mount 會一直指向舊檔。
- **SPA fallback**：`spa-rewrite` 把最後一段沒有副檔名的路徑（含 `/`、`/history`、`/history/`）內部改寫為 `/index.html`，等價於地端 Nginx 的 `try_files $uri $uri/ /index.html`。不使用 custom error response，因其作用於整個 distribution，會讓 `/published/` 下的缺檔回 200 與 HTML。`/api/*`、`/console/*` 不特別處理，落到預報檢視的 not-found 頁。
- **原始碼與測試**：`infra/terraform/functions/spa-rewrite.js` 只宣告頂層 `handler`，由 Terraform `file()` 讀入；同目錄的 `spa-rewrite.test.mjs` 以 `node:vm` 執行同一份原始檔，涵蓋 `/`、`/history`、`/history/`、`/assets/x.js`、`/favicon.ico`、`/console/foo` 與 querystring 原樣保留，由 `scripts/infra_check.sh` 以 `node --test` 執行；該腳本接著對主設定與 bootstrap 層（`infra/terraform/bootstrap/`）檢查 Terraform 格式與已提交的 provider lock 檔、以 `terraform init -backend=false -lockfile=readonly` 驗證設定，再執行 `infra/terraform/tests/` 與 `infra/terraform/bootstrap/tests/` 的 `terraform test`（以 `mock_provider` 執行 `plan`，不需要 AWS 憑證）；本機與 CI 的 `infra` job 都以 `make infra-check` 執行。

## 3. Distribution 其他設定

| 項目 | 設定 |
| :--- | :--- |
| 計費 | 隨用隨付（不訂閱固定費率方案，見 §6） |
| Price class | `PriceClass_200`（`PriceClass_100` 不含台灣與日本的邊緣節點） |
| 網址與憑證 | AWS 預設 `*.cloudfront.net` 與其預設憑證 |
| Viewer protocol | `redirect-to-https` |
| 允許與快取的方法 | `GET`、`HEAD` |
| Default root object | 不設（`/` 由 `spa-rewrite` 改寫為 `/index.html`） |
| Cache key | 不含 headers、cookies 與 query strings |
| 壓縮 | gzip 與 Brotli；預設 behavior 的 cache policy 為 min 0、default 0、max 1 秒（見下方說明） |
| HTTP 版本 | HTTP/2 與 HTTP/3 |
| 安全標頭 | 與 AWS 托管 `SecurityHeadersPolicy` 相同的安全標頭；因每個 behavior 只能掛一個 response headers policy 而併入 §2 的自訂 policy（見下方說明）；不自訂 CSP；地端 Nginx 不跟進 |
| WAF、地理限制、標準 log、custom error response | 皆不設（log 依 ADR-0015 §2.6，custom error response 見 §2） |

- **預設 behavior 的 TTL**：min、default、max TTL 全為 0 的 cache policy 會停用快取，CloudFront 也不接受在這種 policy 上啟用 gzip 與 Brotli；沒有這兩項設定，該 behavior 就不會在邊緣壓縮。因此 max TTL 設為 1 秒並啟用兩種壓縮。上傳端不設 `Cache-Control`，邊緣仍以 default TTL 0 處理，`index.html` 實際上不在邊緣快取。
- **安全標頭的內容**：三個自訂 policy 的 `security_headers_config` 逐項照抄托管 `SecurityHeadersPolicy`（ID `67f7725c-6f97-4210-82d7-5512b31e9d03`，[Using managed response headers policies](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-response-headers-policies.html)）。只有 `X-Content-Type-Options` 覆寫 origin 的值，其餘標頭在 origin 已帶同名標頭時沿用 origin 的值；S3 不送這些標頭，所以回應一律帶下表的值。

  | 標頭 | 值 | 覆寫 origin |
  | :--- | :--- | :--- |
  | `Referrer-Policy` | `strict-origin-when-cross-origin` | 否 |
  | `Strict-Transport-Security` | `max-age=31536000`（不含 `includeSubDomains`、`preload`） | 否 |
  | `X-Content-Type-Options` | `nosniff` | 是 |
  | `X-Frame-Options` | `SAMEORIGIN` | 否 |
  | `X-XSS-Protection` | `1; mode=block` | 否 |

## 4. 前端讀取 `/published/`

- 預報檢視以相對路徑 `/published/` 讀取 JSON，沒有 API base URL 設定；`VITE_API_BASE_URL` 只供工程主控台使用。
- 讀到的 JSON 依[資料契約 §6](data-contracts.md#6-預報檢視公開-jsonpublished) 的 schema 驗證，未知的多餘欄位忽略；非 2xx、網路錯誤、JSON 解析失敗或 schema 不符都視為同一種讀取失敗。尚無已載入的內容時一律顯示中性的錯誤狀態（例如「目前無法取得預報」），不區分原因，不顯示狀態碼或伺服器訊息；已有內容時，背景重新讀取失敗保留原內容，不切換到錯誤狀態。瀏覽器判定離線、請求未送出時比照讀取失敗：尚無內容時顯示同一個中性錯誤狀態，已有內容時保留原內容；恢復連線後自動重新讀取。空狀態只由匯出 JSON 的內容決定（`/` 為 `issued_at` 為 `null`，`/history` 為 `metrics` 為 `null`），不由 HTTP 狀態碼推斷。請求不設快取標頭，快取交給 Nginx 與 CloudFront。
- 重新讀取：`/` 失敗時重試一次；`/history` 的預報實績在背景每 5 分鐘重新讀取一次，失敗不自動重試，由下一次背景讀取恢復。
- 載入中只取決於讀取是否完成。已發布預報在所選預測時效內沒有目標小時（包括 `steps` 為空）時，`/` 顯示一行中性提示，不顯示載入中，也不補造任何列。
- 過舊提示：JSON 內帶 offset 的時刻（`/` 為預報時刻，`/history` 為統計截至時刻）換算成絕對時間後，距觀眾的 `Date.now()` 嚴格超過 24 小時才顯示一行中性提示（例如「預報已超過 24 小時未更新」），正好 24 小時不顯示；提示不揭露、也不暗示原因（ADR-0015 §2.5），舊內容照常顯示，錯誤狀態不顯示。只在渲染時比較，不另設計時器；`/history` 每次背景讀取完成都會重新渲染，內容與前次相同亦然。
- `pnpm dev` 時，預報檢視的 Vite dev server 把 `/published/` 開頭的路徑原樣（不改寫路徑，比對方式同 Nginx 的 `location ^~ /published/`）轉送到地端 Compose 的 Nginx（`:8080`，設定於 `frontend/tooling/vite-dev-proxy.ts`）；預報檢視不設 `/api` proxy。Vitest 以 MSW 攔截 `/published/` 請求並提供 fixtures。

## 5. 部署與驗證

- **上傳順序**：先上傳 `site/assets/*`，再上傳 `site/index.html`；舊 assets 以 `sync --delete` 立即刪除，被刪物件依 ADR-0015 §2.6 的版本規則 30 天後過期。
- **不做 invalidation**：`index.html` 邊緣不快取、assets 帶 hash，部署後不需 CloudFront invalidation。
- **雲端 smoke check**：除 ADR-0015 §4 的項目（首頁與兩份 JSON 回 200、預報時刻不超過 24 小時）外，另驗證：
  - `/history` 回 200 且為 HTML；
  - `/published/` 下不存在的檔案不回 200。
- **smoke check 腳本**：`scripts/smoke_cloudfront.py`，只用 Python 標準函式庫，以 `make cloud-smoke ARGS="--base-url <forecast_view_url>"` 或 `uv run --no-project python scripts/smoke_cloudfront.py --base-url <url>` 執行；CI 的部署 job 不下載 uv，改以 `scripts/smoke_cloudfront.sh --base-url <url>` 用 `python3` 執行（[Terraform state 與部署權責 §9](terraform-state-and-deployment.md#9-cd-部署-main)）。
  - `--base-url` 為必填；`--now` 為選填（ISO 8601 帶 offset，預設為執行當下）。
  - 每一項都執行，最後列出所有未通過的項目與實際狀態碼或原因。結束碼：全部通過為 0，任一項失敗為 1，參數錯誤為 2；經 `make` 執行時，任何非 0 都由 `make` 回報為 2，CD 管線須區分時直接執行腳本。
  - 不跟隨 redirect，任何 3xx 都算該項失敗；不檢查 `Cache-Control`、安全標頭，也不檢查預報時刻是否晚於當下。
- **CD 管線**：`main` push 後的 apply、上傳與 smoke check 的順序、觸發條件與略過條件見 [Terraform state 與部署權責 §9](terraform-state-and-deployment.md#9-cd-部署-main)。

## 6. 固定費率方案的重新評估條件

CloudFront 固定費率 Free 方案（每月 0 美元、額度為 100 萬次請求與 100 GB 傳輸；超量不收費，持續超量時改為調整傳遞）可為月費設硬性上限，但 M4 不採用。下列前提已於 2026-11-21 以 AWS 原頁複核（[GitHub #168](https://github.com/shiroki9979/shiro-mlops/issues/168)，主要為 [Flat-rate pricing plans](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/flat-rate-pricing-plan.html)）；標為「未證實」的項目，原頁沒有明文，重新評估時仍須向 AWS 確認：

- **未證實**：只用 `*.cloudfront.net`、不掛自訂網域的 distribution 可以訂閱。原頁只寫每個方案涵蓋一個 distribution 與「最多一個」apex 網域。
- 使用 AWS Free Tier 的帳號不能訂閱（即 Free 帳號方案不可訂閱）。
- Terraform AWS provider 須升級至 ≥ 6.69（`aws_pricingplanmanager_subscription`），現行為 `~> 5.0`。
- 每個訂閱必須綁定一個 WAF web ACL，distribution 須使用 cache policy 與 OAC。訂閱期間無法刪除 distribution，`terraform destroy` 須先取消訂閱；Free 方案取消即時生效。
- 與該 distribution 關聯的資源（例如 `spa-rewrite`）不能與其他 distribution 共用；使用 Shield Advanced 或 Firewall Manager 的 distribution 不能訂閱。
- 每個帳號最多 3 個 Free 方案，每個方案一個 distribution。
- **未證實**：方案不能設定 price class，邊緣節點由 AWS 決定。原頁未提及 price class，只寫方案涵蓋全球傳遞。
