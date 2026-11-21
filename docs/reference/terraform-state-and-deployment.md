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
