# Terraform state 與部署權責

- 建立日期：2026-11-21
- 最後更新：2026-11-21
- 專案版本：`0.4.0`

---

依 [ADR-0015](../adr/0015-publish-forecast-view-as-static-precomputed-output.md)，雲端只有預報檢視的靜態託管資源。本文件記錄這些資源的 Terraform 分層、state 的存放與鎖定，以及 GitHub Actions 三個 OIDC 角色的信任與權限；決策經 [GitHub #129](https://github.com/shiroki9979/shiro-mlops/issues/129) 定案，實作於 [GitHub #186](https://github.com/shiroki9979/shiro-mlops/issues/186)。部署與拆除的操作步驟見[如何部署 AWS 基礎設施](../how-to/deploy-aws-infrastructure.md)。

## 1. 兩層結構

| 層 | 目錄 | 資源 | 由誰 apply |
| :--- | :--- | :--- | :--- |
| bootstrap 層 | `infra/terraform/bootstrap/` | state bucket、GitHub OIDC provider、plan 角色、apply 角色及其 policy | 只由人以 IAM Identity Center 的管理員短期憑證在本機 apply；CI 沒有任何角色能修改它 |
| 主設定 | `infra/terraform/` | 預報檢視的 bucket、CloudFront、網站上傳角色、地端上傳用 IAM 使用者、AWS Budgets | CI 以 apply 角色 apply；需要刪除或替換資源時由人在本機 apply |

- 主設定不建立 OIDC provider，以 data source `aws_iam_openid_connect_provider` 依 URL `https://token.actions.githubusercontent.com` 引用 bootstrap 層建立的 provider；因此必須先 apply bootstrap 層。
- Terraform 只管理長期資源；`site/` 與 `published/` 的物件不由 Terraform 管理。
- 帳號 ID 一律由目前憑證的身分（`aws_caller_identity`）推得，沒有對應的變數。
- 變數 `github_repo` 在兩層都預設為 `shiroki9979/shiro-mlops`，是所有角色信任條件中的儲存庫名稱。

## 2. State 與鎖定

兩層的 state 都放在 bootstrap 層建立的同一個 state bucket，以不同 key 區分：

| 層 | state key | lockfile |
| :--- | :--- | :--- |
| bootstrap 層 | `bootstrap/terraform.tfstate` | `bootstrap/terraform.tfstate.tflock` |
| 主設定 | `forecast-view/terraform.tfstate` | `forecast-view/terraform.tfstate.tflock` |

- **state bucket**：名稱為 `shiro-mlops-tfstate-<帳號 ID>`（含帳號 ID 以確保全域唯一），位於 `ap-northeast-1`；開啟 versioning、以 SSE-S3（`AES256`）預設加密，public access block 四項全開。bootstrap 層輸出 `state_bucket_name`。
- **與預報檢視 bucket 分開**：CloudFront 讀不到 state，預報檢視 bucket 的 30 天舊版本過期規則也不會刪掉 state 的舊版本；state 損壞時以 bucket 的舊版本復原。
- **鎖定**：兩層的 backend 都設定 `use_lockfile = true`，以 S3 原生 lockfile 鎖定，不使用 DynamoDB。原生 lockfile 自 Terraform 1.11 GA，兩層的 `required_version` 因此為 `>= 1.11.0`；AWS provider 為 `~> 5.0`。
- **backend 採 partial configuration**：backend 區塊只寫 `key`、`region`、`encrypt` 與 `use_lockfile`，bucket 名稱不寫進程式碼。本機以不提交的 backend 設定檔 `infra/terraform/state.s3.tfbackend`（內容只有一行 `bucket = "<state_bucket_name>"`，兩層共用；`.gitignore` 已排除 `*.tfbackend`）以 `-backend-config` 傳入。
- **bootstrap 層的雞生蛋問題**：state bucket 由 bootstrap 層自己建立，因此 bootstrap 層第一次以本機 state apply，再以 `terraform init -migrate-state` 把 state 搬進 state bucket 的 `bootstrap/terraform.tfstate`。拆除時反向把 state 搬回本機。本機 state 以不提交的 `backend_override.tf`（`.gitignore` 已排除 `*_override.tf`）切換。
- **離線檢查**：`make infra-check` 對兩層都以 `terraform init -backend=false` 初始化，不讀 state，也不需要 AWS 憑證。

## 3. 角色的信任與權限

三個角色都只接受 `token.actions.githubusercontent.com:aud` 為 `sts.amazonaws.com` 的 token，且以 `StringEquals` 比對單一的 `sub`；任何角色都不接受 `repo:<repo>:*`。

| 角色 | 名稱（輸出） | 信任的 `sub` | 權限 |
| :--- | :--- | :--- | :--- |
| plan 角色（bootstrap 層） | `shiro-mlops-terraform-plan`（`terraform_plan_role_arn`） | `repo:shiroki9979/shiro-mlops:pull_request` | AWS 託管 `ReadOnlyAccess`；另以 inline policy 允許 state bucket 的 `s3:ListBucket` 與主設定 state key 的 `s3:GetObject`。沒有任何寫入權限，也沒有 lockfile 權限 |
| apply 角色（bootstrap 層） | `shiro-mlops-terraform-apply`（`terraform_apply_role_arn`） | `repo:shiroki9979/shiro-mlops:ref:refs/heads/main` | 見下方 |
| 網站上傳角色（主設定） | `shiro-mlops-site-deploy`（`site_deploy_role_arn`） | 同 apply 角色 | 只能列出、寫入與刪除預報檢視 bucket 的 `site/*`（[預報檢視的雲端託管 §1](forecast-view-hosting.md#1-s3-配置與寫入權限)） |

- **plan 角色**：任何 PR 都能 assume，因此不得有寫入權限；PR 上的 plan 以 `-lock=false` 執行，不需要寫 lockfile。`ReadOnlyAccess` 目前已涵蓋 state 的讀取，inline policy 讓 AWS 日後縮減託管 policy 的 S3 讀取時 plan 仍可運作。
- **apply 角色**：只有合併進 `main` 的程式碼能 assume。inline policy `shiro-mlops-terraform-apply` 的 statement：

  | Sid | 效果 | 內容 |
  | :--- | :--- | :--- |
  | `ManageS3` | Allow | `s3:*`，以 `NotResource` 排除 state bucket 與其所有物件 |
  | `ListStateBucket` | Allow | state bucket 的 `s3:ListBucket` |
  | `ReadWriteForecastViewState` | Allow | `forecast-view/terraform.tfstate` 與其 `.tflock` 的 `s3:GetObject`、`s3:PutObject`、`s3:DeleteObject` |
  | `ManageCloudFront` | Allow | `cloudfront:*` |
  | `ManageBudgets` | Allow | `budgets:*` |
  | `ManageProjectIam` | Allow | `iam:*`，只限名稱為 `shiro-mlops-*` 的 role、policy 與 user |
  | `LookUpOidcProvider` | Allow | `iam:GetOpenIDConnectProvider`、`iam:ListOpenIDConnectProviderTags`、`iam:ListOpenIDConnectProviders`（主設定的 data source 依 URL 查找 provider） |
  | `DenyStateBucketChanges` | Deny | state bucket 本身除 `s3:ListBucket` 以外的所有動作：刪除 bucket、修改 versioning、加密、public access block、bucket policy 等設定 |
  | `DenyOidcProviderChanges` | Deny | OIDC provider 除 `iam:GetOpenIDConnectProvider` 與 `iam:ListOpenIDConnectProviderTags` 以外的所有動作 |
  | `DenyBootstrapRoles` | Deny | plan 與 apply 角色本身的 `iam:*` |

  apply 角色因此碰不到 bootstrap 層的 state，也無法放寬自己或 plan 角色的信任與權限。policy 採 inline 而非 managed：名稱為 `shiro-mlops-*` 的 managed policy 會落在 `ManageProjectIam` 內，角色就能為自己的 policy 發布更寬的版本。
- **網站上傳角色**：與地端上傳用 IAM 使用者的 `published/*` 權限互不重疊。

### 殘餘風險

不加 permissions boundary。apply 角色仍可建立名稱為 `shiro-mlops-*` 的新角色、讓它信任任意主體並掛上高權限 policy（例如 `AdministratorAccess`），再 assume 它取得帳號的完整權限。這需要合併進 `main` 的程式碼或遭竊的 `main` workflow token；此風險已接受，影響範圍仍小於直接給 apply 角色 `AdministratorAccess`。apply 角色也能為地端上傳用 IAM 使用者建立 access key。

## 4. 離線驗證

`make infra-check`（`scripts/infra_check.sh`）對兩層都執行 `terraform fmt -check`、`terraform validate`（`init -backend=false`）與 `terraform test`。`terraform test` 以 `mock_provider "aws"` 執行 `plan`，不需要 AWS 憑證或 state backend；斷言的項目見 `infra/terraform/tests/` 與 `infra/terraform/bootstrap/tests/`：

- plan、apply 與網站上傳角色的 `sub` 與 `aud` 各等於第 3 節的值，沒有 `repo:<repo>:*`；網站上傳角色信任 data source 引用的 provider。
- plan 角色只有 `ReadOnlyAccess` 與 state 的列出、讀取。
- apply 角色的 IAM 權限只限 `shiro-mlops-*`，並對 state bucket、OIDC provider、plan 與 apply 角色有明確 Deny；在 state bucket 內只能存取主設定的 state 與 lockfile。
- state bucket 開啟 versioning、SSE 與完整的 public access block。
- 網站上傳角色只能寫 `site/*`；`budget_alert_email` 為 sensitive。

## 5. CD 部署 (main)

`.github/workflows/ci.yml` 的 `deploy` job 在 release 合併到 `main` 後 apply 主設定並部署預報檢視；實作於 [GitHub #188](https://github.com/shiroki9979/shiro-mlops/issues/188)。這個 job 的順序、`needs` 與 `concurrency` 不做離線測試，由營運驗收的第一次 release 驗證。

- **觸發條件**：只在 `main` 分支的 push 執行；每次 push 都執行，不加 path filter，沒有基礎設施變更時 apply 是 no-op，同時能發現 drift。
- **`needs`**：`lint-and-test`、`frontend`、`nginx`、`infra`、`docs` 全部通過才執行，任一失敗就不部署。不依賴 PR plan job：它只在 pull request 執行，push 時被略過，依賴被略過的 job 會讓部署 job 一起被略過。
- **權限**：只有這個 job 授予 `id-token: write`（另有 `contents: read`）；workflow 層級不另授權限。

步驟依序執行，任一步失敗即停止：

| 順序 | 角色 | 步驟 |
| :--- | :--- | :--- |
| 1 | apply 角色 | 對主設定 `terraform init`（state bucket 以 `-backend-config="bucket=…"` 從 repository variable `TF_STATE_BUCKET` 傳入）→ `plan -out=tfplan`（取得 lockfile）→ `show -json` → plan 安全檢查（摘要寫進 job summary）→ `apply tfplan`。套用的是剛通過檢查的那份已存 plan；含刪除、替換或 `forget` 時檢查以結束碼 1 失敗，不 apply |
| 2 | apply 角色 | 以 `terraform output -raw` 讀取 `s3_bucket_name` 與 `forecast_view_url`；網站上傳角色讀不到 state，因此在換角色前讀取 |
| 3 | 無 | 建置預報檢視（`pnpm --filter @shiro-mlops/forecast-view run build`） |
| 4 | 網站上傳角色 | `scripts/upload_forecast_view_site.sh` 依[預報檢視的雲端託管 §5](forecast-view-hosting.md#5-部署與驗證) 上傳 `site/`：先上傳 `index.html` 以外的檔案，再上傳 `index.html`，最後以 `sync --delete` 刪除前一版的 assets；不做 invalidation。建置目錄沒有 `index.html` 時以結束碼 2 停止，不執行 `sync --delete` |
| 5 | 無 | 以 `forecast_view_url` 直接執行 `scripts/smoke_cloudfront.py`，跑完整項目（含 `/published/` 新鮮度） |

`budget_alert_email` 由 Actions secret `BUDGET_ALERT_EMAIL` 以環境變數 `TF_VAR_budget_alert_email` 傳入；變數與 secret 的完整清單見本文件「Repository variables 與 secrets」一節。

- **串行**：`concurrency` group `deploy-forecast-view`，`cancel-in-progress: false`，兩次部署不會同時寫 state 或 `site/`，執行中的部署不會被取消。GitHub 每個 group 只保留一個等待中的執行，排隊期間又有新的 push 時，較舊的等待中執行會被取消，由較新的 `main` 取代。
- **失敗不回滾**：任一步失敗只讓 workflow 失敗。apply 之後的步驟失敗時，已套用的基礎設施變更與已上傳的 `site/` 維持原狀；需要復原時由人以 bucket 的舊版本手動處理。plan 含刪除或替換時改由人在本機 apply（第 1 節）。
- **略過條件**：repository variable `AWS_TERRAFORM_APPLY_ROLE_ARN` 未設定時，job 的第一步寫一行 `::notice::` 與一行 job summary，其餘步驟都不執行，job 以成功結束，`main` 不因尚未開通 AWS 而變紅。營運驗收設定這個變數後，下一次 `main` push 起自動部署；其他變數或 secret 缺漏時，對應步驟失敗。
