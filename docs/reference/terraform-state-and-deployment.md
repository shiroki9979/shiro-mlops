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

## 5. Plan 安全檢查

`scripts/check_plan_safety.py` 判斷 CI 能否套用一份已存 plan，只用 Python 標準函式庫，PR plan 與 `main` 的部署 job 都呼叫它：

```bash
terraform show -json tfplan > tfplan.json
uv run --no-project python scripts/check_plan_safety.py tfplan.json
```

- **輸入**：`terraform show -json` 對已存 plan 的輸出。沒有任何資源的設定不含 `resource_changes`，視為沒有變更。
- **規則採白名單**：每個 resource change 的 `actions` 只能由 `no-op`、`create`、`read`、`update` 組成。出現 `delete`（包括替換時的 `delete`＋`create` 與 `create`＋`delete`）或 `forget`（從 state 移除）都視為不安全，其他未知的動作也一樣。
- **輸出**：stdout 為 Markdown 摘要，寫進 job summary：結果（safe／unsafe）、各類動作的計數表與資源位址；不安全時另列出每個違規的資源位址與動作。摘要只含資源位址與動作，不含屬性值。錯誤訊息寫到 stderr。

| 結束碼 | 意義 |
| :--- | :--- |
| `0` | 安全：沒有刪除、替換或 `forget` |
| `1` | 不安全：至少一個 resource change 刪除、替換或 `forget` 資源 |
| `2` | 參數錯誤、檔案無法讀取、JSON 無法解析，或不是 `terraform show -json` 的 plan |

## 6. PR plan

`.github/workflows/ci.yml` 的 `terraform-plan` job 讓 release 審查者在合併前看到雲端會怎麼變：

- **觸發**：只在 base 為 `main` 的 PR（`dev` → `main` 的 release PR）執行；base 為 `dev` 的 PR 不執行。
- **權限**：只有這個 job 取得 `id-token: write`，以 GitHub OIDC assume plan 角色（第 3 節）；plan 角色沒有寫入權限，因此 plan 以 `-lock=false` 執行，不寫 lockfile。
- **步驟**：對主設定執行 `terraform init -backend-config="bucket=<TF_STATE_BUCKET>"`、`terraform plan -lock=false -out=tfplan`、`terraform show -json tfplan`，再以第 5 節的腳本判斷。
- **結果**：摘要出現在 job summary，不寫 PR comment，因此不需要 `pull-requests: write` 或第三方 action。plan 不安全時 job 失敗，摘要列出違規資源。
- **`budget_alert_email`**：只由 Actions secret `BUDGET_ALERT_EMAIL` 以 `TF_VAR_budget_alert_email` 傳入。變數標為 sensitive，plan 輸出顯示為 `(sensitive value)`；已存 plan 與其 JSON 含明文，只留在 runner 上，不上傳為 artifact。
- **AWS 尚未設定時略過**：repository variable `AWS_TERRAFORM_PLAN_ROLE_ARN` 未設定時，job 寫一行 notice 與 job summary「AWS 尚未設定，略過 Terraform plan」後成功結束，PR 不因此變紅；營運驗收設定變數後自動啟用。

## 7. 需要刪除或替換時

CI 不套用含刪除、替換或 `forget` 的 plan，這類變更一律由人執行：

1. 以 IAM Identity Center 的管理員短期憑證登入（見[如何部署 AWS 基礎設施](../how-to/deploy-aws-infrastructure.md)）。
2. 在本機 checkout release PR 的 head，也就是 `dev` 的程式碼，在 `infra/terraform/` 以 `terraform init -backend-config=state.s3.tfbackend` 連上遠端 state 後執行 `terraform plan`，確認刪除或替換的資源正是預期的那些，再 `terraform apply`。本機 apply 會寫 lockfile，與 CI 的 apply 互斥。
3. 重跑 release PR 的 `terraform-plan` job。state 已反映變更，plan 不再含刪除或替換，job 轉綠後才合併。

替換 CloudFront distribution 會改變公開的 `*.cloudfront.net` 網址；合併前確認這是刻意的變更。`terraform destroy` 與既有的拆除步驟不經 CI，照舊在本機執行。

## 8. Repository variables 與 secrets

CI 用到的值都放在 GitHub 的 **Settings > Secrets and variables > Actions**。非機密值放 repository variables，機密值放 Actions secrets；來源都是 Terraform 的輸出或營運者自己的設定。

| 名稱 | 種類 | 值的來源 | 使用的 job |
| :--- | :--- | :--- | :--- |
| `AWS_REGION` | variable | `ap-northeast-1` | `terraform-plan`、`deploy` |
| `TF_STATE_BUCKET` | variable | bootstrap 層輸出 `state_bucket_name` | `terraform-plan`、`deploy` |
| `AWS_TERRAFORM_PLAN_ROLE_ARN` | variable | bootstrap 層輸出 `terraform_plan_role_arn` | `terraform-plan` |
| `AWS_TERRAFORM_APPLY_ROLE_ARN` | variable | bootstrap 層輸出 `terraform_apply_role_arn` | `deploy` |
| `AWS_SITE_DEPLOY_ROLE_ARN` | variable | 主設定輸出 `site_deploy_role_arn` | `deploy` |
| `BUDGET_ALERT_EMAIL` | secret | 接收 AWS Budgets 成本警示的 email；以 `TF_VAR_budget_alert_email` 傳入 | `terraform-plan`、`deploy` |

job 所需的角色 ARN variable 未設定時，該 job 寫 notice 後略過並成功結束。
