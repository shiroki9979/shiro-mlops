# 如何部署 AWS 基礎設施 (Terraform & IAM OIDC)

- 建立日期：2026-08-23
- 最後更新：2026-11-21

> [!NOTE]
> **Diátaxis 象限鎖定**
>
> - **目標象限**：How-To Guide
> - **目標讀者**：負責雲端基礎設施部署的 MLOps / DevOps 工程師
> - **核心目標**：指引如何以 IAM Identity Center 的短期憑證建立 Terraform 的 bootstrap 層與 S3 遠端 state、首次 apply 預報檢視的靜態託管資源（S3 與 CloudFront）、建立與輪替地端上傳用 access key、設定 CI 使用的 GitHub variables 與 secrets、取得預報檢視的網址與執行雲端 smoke check，以及依序拆除兩層
> - **排除內容（Avoid）**：AWS 基本概念入門、AWS Organizations 與 IAM Identity Center 的開通、本機快速預測操作、CD 管線設定

依 [ADR-0015](../adr/0015-publish-forecast-view-as-static-precomputed-output.md)，雲端只存放並提供預報檢視的發布產物。Terraform 分成兩層，結構、state 與各角色的信任與權限見 [Terraform state 與部署權責](../reference/terraform-state-and-deployment.md)：

- **bootstrap 層**（`infra/terraform/bootstrap/`）：只由人手動 apply。
  - state bucket（名稱見輸出 `state_bucket_name`）：存放兩層的 state。
  - GitHub Actions OIDC provider。
  - plan 角色 `shiro-mlops-terraform-plan`：只信任 PR 的 token，唯讀。
  - apply 角色 `shiro-mlops-terraform-apply`：只信任 `main` 分支 push 的 token，用來 apply 主設定。
- **主設定**（`infra/terraform/`）：
  - S3 bucket（名稱取自變數 `s3_bucket_name`）：`site/` 放前端建置產物、`published/` 放匯出的 JSON（配置見[預報檢視的雲端託管 §1](../reference/forecast-view-hosting.md#1-s3-配置與寫入權限)）；保留 versioning，舊版本 30 天後過期。
  - 網站上傳角色 `shiro-mlops-site-deploy`：信任 bootstrap 層建立的 OIDC provider，只接受 `shiroki9979/shiro-mlops` 的 `main` 分支 push 所取得的 token，只能列出、寫入與刪除 `site/*`。
  - 地端上傳用 IAM 使用者（名稱見輸出 `onprem_publisher_user_name`）：只能 `PutObject` 到 `published/*`。
  - CloudFront distribution：經 Origin Access Control（OAC）讀取 bucket 的 `site/` 與 `published/`，含 SPA 改寫函式 `spa-rewrite` 與各 behavior 的 cache policy（配置見[預報檢視的雲端託管 §2](../reference/forecast-view-hosting.md#2-origin-與-behavior)、[§3](../reference/forecast-view-hosting.md#3-distribution-其他設定)）；bucket policy 只授權這個 distribution 讀取這兩個 prefix。
  - AWS Budgets：月實際支出達 5 美元、預測支出達 10 美元時寄 email 警示。

第 3 節與第 9 節「拆除 bootstrap 層」的指令從 `infra/terraform/bootstrap/` 執行，第 4 節以後的其餘指令從 `infra/terraform/` 執行：bucket、使用者與 region 一律以 `terraform output` 從該目錄的 state 取值，不另行手寫。

---

## 1. 前置準備

- 已安裝 [Terraform](https://developer.hashicorp.com/terraform/downloads) ($\ge 1.11.0$) 與 AWS CLI v2
- AWS 帳號為 Paid 方案，已以該帳號為 management account 建立 AWS Organizations 與 IAM Identity Center organization instance，並把 `AdministratorAccess` permission set 指派給自己；root 只開 MFA，不用來執行本指南
- 已確定目標 GitHub Repository 名稱；兩層的變數 `github_repo` 都預設為 `shiroki9979/shiro-mlops`，部署其他 repository 時才需覆寫
- 已確定接收成本警示的 email 地址

---

## 2. 以 IAM Identity Center 取得管理員短期憑證

除第 6 節以地端 key 執行的權限確認外，本指南的指令都以這組短期憑證執行，工作站上不放長期的管理員 key。

1. **建立 profile**（每台工作站一次）：依提示填入 Identity Center 的 start URL 與區域，選擇目標帳號與 `AdministratorAccess` permission set；以下假設 profile 名稱為 `shiro-admin`：

   ```bash
   aws configure sso
   ```

2. **登入並使用該 profile**：憑證過期後重新執行 `aws sso login` 即可：

   ```bash
   aws sso login --profile shiro-admin
   export AWS_PROFILE=shiro-admin
   ```

3. **確認身分**：輸出的 `Arn` 應含 `AWSReservedSSO_AdministratorAccess`：

   ```bash
   aws sts get-caller-identity
   ```

---

## 3. 建立 bootstrap 層並把 state 搬進 state bucket

state bucket 由 bootstrap 層自己建立，因此第一次以本機 state apply，再把 state 搬進 state bucket。

1. **以本機 state 初始化**：從 repository 根目錄切換至 `infra/terraform/bootstrap/`，建立暫時的 `backend_override.tf` 改用本機 backend（`.gitignore` 已排除 `*_override.tf`）：

   ```bash
   cd infra/terraform/bootstrap
   cat <<'EOF' > backend_override.tf
   terraform {
     backend "local" {}
   }
   EOF
   terraform init
   ```

2. **預覽並套用**：plan 應只有新增，沒有修改或刪除：

   ```bash
   terraform plan
   terraform apply
   ```

3. **建立 backend 設定檔**：兩層共用 `infra/terraform/state.s3.tfbackend`，內容只有 state bucket 名稱（`.gitignore` 已排除 `*.tfbackend`，勿提交）：

   ```bash
   echo "bucket = \"$(terraform output -raw state_bucket_name)\"" > ../state.s3.tfbackend
   ```

4. **把 state 搬進 state bucket**：刪除 `backend_override.tf` 後以 `-migrate-state` 初始化，詢問是否複製既有 state 時回答 `yes`：

   ```bash
   rm backend_override.tf
   terraform init -migrate-state -backend-config=../state.s3.tfbackend
   ```

5. **確認並刪除本機 state**：以下指令應印出 `bootstrap/terraform.tfstate`，`terraform plan` 應顯示 `No changes.`；確認後刪除本機的 state 檔：

   ```bash
   aws s3 ls "s3://$(terraform output -raw state_bucket_name)/bootstrap/"
   terraform plan
   rm terraform.tfstate terraform.tfstate.backup
   ```

之後修改 bootstrap 層時，同樣以第 2 節的短期憑證在這個目錄執行 `terraform plan` 與 `terraform apply`；CI 沒有任何角色能修改它。

---

## 4. 主設定首次 apply

1. **配置 Terraform 變數**：切換至 `infra/terraform/` 並建立 `terraform.tfvars`（`.gitignore` 已排除 `*.tfvars`）：

   ```bash
   cd ..
   cat <<EOF > terraform.tfvars
   aws_region         = "ap-northeast-1"
   environment        = "dev"
   s3_bucket_name     = "shiro-mlops-forecast-view"
   github_repo        = "shiroki9979/shiro-mlops"
   budget_alert_email = "ops@example.com"
   EOF
   ```

   `budget_alert_email` 沒有預設值，必須提供；它標為 sensitive，`plan` 與 `apply` 的輸出不會顯示這個地址。AWS 帳號 ID 由目前憑證的身分取得，不需要設定變數。

2. **以 backend 設定檔初始化**：曾以 `make infra-check` 或 `terraform init -backend=false` 初始化過這個目錄時，加上 `-reconfigure`：

   ```bash
   terraform init -backend-config=state.s3.tfbackend
   ```

3. **預覽並套用**：主設定以 data source 引用第 3 節建立的 OIDC provider，bootstrap 層尚未 apply 時 plan 會失敗：

   ```bash
   terraform plan
   terraform apply
   ```

首次 apply 之後，主設定的變更由 CI 以 apply 角色套用；需要刪除或替換資源時由人在本機以第 2 節的憑證執行（權責見 [Terraform state 與部署權責 §1](../reference/terraform-state-and-deployment.md#1-兩層結構)）。

---

## 5. 取得輸出並設定 GitHub Variables 與 Secrets

主設定 apply 完成後，Terraform 會輸出以下值（bootstrap 層的輸出 `state_bucket_name`、`terraform_plan_role_arn` 與 `terraform_apply_role_arn` 在 `infra/terraform/bootstrap/` 以 `terraform output` 取得）：

- `s3_bucket_name`
- `aws_region`
- `site_deploy_role_arn`
- `onprem_publisher_user_name`
- `forecast_view_url`
- `cloudfront_distribution_id`

前往 GitHub Repository 設置（**Settings > Secrets and variables > Actions**），新增以下 Repository Variables 與 Actions secret（各值的用途見 [Terraform state 與部署權責 §8](../reference/terraform-state-and-deployment.md#8-repository-variables-與-secrets)）：

- Repository Variables：
  - `AWS_REGION`: `ap-northeast-1`
  - `TF_STATE_BUCKET`: `<bootstrap 層 state_bucket_name 輸出值>`
  - `AWS_TERRAFORM_PLAN_ROLE_ARN`: `<bootstrap 層 terraform_plan_role_arn 輸出值>`
  - `AWS_SITE_DEPLOY_ROLE_ARN`: `<site_deploy_role_arn 輸出值>`
  - `AWS_TERRAFORM_APPLY_ROLE_ARN`: `<bootstrap 層 terraform_apply_role_arn 輸出值>`；最後設定，見下方提醒
- Actions secret：
  - `BUDGET_ALERT_EMAIL`: 與第 4 節 `terraform.tfvars` 的 `budget_alert_email` 相同

設定 `AWS_TERRAFORM_PLAN_ROLE_ARN` 後，base 為 `main` 的 PR 會附上主設定的 plan 摘要。plan 角色只接受 PR 的 token；apply 角色與網站上傳角色只接受 `main` 分支 push 的 workflow 執行，PR 或其他分支的 workflow 無法 assume。

> [!IMPORTANT]
> **第一次 release 前，地端 key 與匯出須先上線**：設定 `AWS_TERRAFORM_APPLY_ROLE_ARN` 後，每次 `main` push 都會 apply、上傳 `site/` 並執行雲端 smoke check（見 [Terraform state 與部署權責 §9](../reference/terraform-state-and-deployment.md#9-cd-部署-main)）。先依第 6 節建立地端 access key，並確認匯出已上傳到 `published/`，再設定這個變數並合併第一次 release；否則 smoke check 的 `/published/` JSON 與預報時刻新鮮度項目會失敗，workflow 標紅。

---

## 6. 建立地端上傳用 access key

access key 由人工建立與輪替，不經 Terraform（見 [ADR-0015 §2.3](../adr/0015-publish-forecast-view-as-static-precomputed-output.md#23-地端到雲端的匯出)）。以第 2 節的管理員短期憑證建立：

```bash
aws iam create-access-key \
  --user-name "$(terraform output -raw onprem_publisher_user_name)"
```

把回傳的 `AccessKeyId` 與 `SecretAccessKey` 寫入地端主機的 `.env`（勿提交），`FORECAST_VIEW_S3_BUCKET` 填 `terraform output -raw s3_bucket_name` 的值，`AWS_DEFAULT_REGION` 填 `terraform output -raw aws_region` 的值。`FORECAST_VIEW_S3_BUCKET` 留空時匯出只寫地端目錄，不會上傳：

```dotenv
FORECAST_VIEW_S3_BUCKET=<s3_bucket_name 輸出值>
AWS_ACCESS_KEY_ID=<AccessKeyId>
AWS_SECRET_ACCESS_KEY=<SecretAccessKey>
AWS_DEFAULT_REGION=<aws_region 輸出值>
```

確認 key 只能寫入 `published/`。兩個上傳指令以新 key 執行：第一個應印出 `upload:`，第二個應回 `AccessDenied`：

```bash
BUCKET="$(terraform output -raw s3_bucket_name)"
echo '{}' > /tmp/probe.json
AWS_ACCESS_KEY_ID=<AccessKeyId> AWS_SECRET_ACCESS_KEY=<SecretAccessKey> \
  aws s3 cp /tmp/probe.json "s3://$BUCKET/published/probe.json"
AWS_ACCESS_KEY_ID=<AccessKeyId> AWS_SECRET_ACCESS_KEY=<SecretAccessKey> \
  aws s3 cp /tmp/probe.json "s3://$BUCKET/site/probe.json"
```

`published/` 會公開提供，且這把 key 不能刪除物件。確認後以管理員短期憑證逐一刪除 `published/probe.json` 的所有版本；指定 `--version-id` 是永久刪除，不會留下 delete marker：

```bash
BUCKET="$(terraform output -raw s3_bucket_name)"
for v in $(aws s3api list-object-versions --bucket "$BUCKET" \
    --prefix published/probe.json \
    --query "Versions[?Key=='published/probe.json'].VersionId" --output text); do
  aws s3api delete-object --bucket "$BUCKET" \
    --key published/probe.json --version-id "$v"
done
```

再執行一次迴圈中的 `list-object-versions`，應沒有任何輸出。

最後在地端專案根目錄重建執行匯出的 `dagster-webserver` 容器，讓它讀入 `.env` 的新設定（`restart` 不會重新讀取 `.env`）：

```bash
docker compose --env-file .env -f docker/docker-compose.yml up -d --force-recreate dagster-webserver
```

下一次每小時匯出（每小時第 35 分）後，地端 Dagster 中 `forecast_view_export` 的 materialization metadata `uploaded_to_s3` 應為 `true`。

---

## 7. 輪替地端 access key

IAM 使用者最多同時有兩把 access key，輪替時先建新 key、確認可用後再停用舊 key：

1. **建立新 key**：以第 6 節的 `create-access-key` 指令建立。

2. **更新地端 `.env`**：換上新的 `AWS_ACCESS_KEY_ID` 與 `AWS_SECRET_ACCESS_KEY`，重建執行匯出的 `dagster-webserver` 容器（`restart` 不會重新讀取 `.env`），確認下一次每小時匯出成功上傳（地端 Dagster 執行紀錄無錯誤）：

   ```bash
   docker compose --env-file .env -f docker/docker-compose.yml up -d --force-recreate dagster-webserver
   ```

3. **停用舊 key**：列出 key，找出舊的 `AccessKeyId` 並停用：

   ```bash
   aws iam list-access-keys \
     --user-name "$(terraform output -raw onprem_publisher_user_name)"
   aws iam update-access-key \
     --user-name "$(terraform output -raw onprem_publisher_user_name)" \
     --access-key-id <舊 AccessKeyId> --status Inactive
   ```

4. **刪除舊 key**：觀察一段時間確認沒有服務仍使用舊 key 後刪除：

   ```bash
   aws iam delete-access-key \
     --user-name "$(terraform output -raw onprem_publisher_user_name)" \
     --access-key-id <舊 AccessKeyId>
   ```

懷疑 key 外洩時，依步驟 3、4 直接停用並刪除外洩的 key，再依第 6 節建立新 key。外洩的影響範圍與復原方式見 [ADR-0015 §2.3](../adr/0015-publish-forecast-view-as-static-precomputed-output.md#23-地端到雲端的匯出)。

---

## 8. 取得預報檢視網址

預報檢視以 AWS 預設的 `*.cloudfront.net` 網址提供，以 `terraform output` 取得完整的 `https://` 網址：

```bash
terraform output -raw forecast_view_url
```

首次建立 distribution 時，`terraform apply` 會等到 distribution 部署完成才結束，可能需要數分鐘。之後若要確認狀態，以下指令應印出 `Deployed`：

```bash
aws cloudfront get-distribution \
  --id "$(terraform output -raw cloudfront_distribution_id)" \
  --query Distribution.Status --output text
```

bucket 剛建立時 `site/` 與 `published/` 都是空的，缺檔回 403 屬預期結果，不是設定錯誤（原因見[預報檢視的雲端託管 §1](../reference/forecast-view-hosting.md#1-s3-配置與寫入權限)）：

- `site/` 還沒上傳前，首頁 `/` 與 `/history` 回 403。
- `published/` 還沒上傳前，`/published/` 下的 JSON 回 403；第 6 節的地端匯出上傳後，約一分鐘內生效。

### 執行雲端 smoke check

以 `forecast_view_url` 的值，透過 repo 根目錄的 Makefile target 驗證網址符合[預報檢視的雲端託管 §5](../reference/forecast-view-hosting.md#5-部署與驗證)：

```bash
make -C ../.. cloud-smoke ARGS="--base-url $(terraform output -raw forecast_view_url)"
```

腳本只用 Python 標準函式庫，不需先執行 `uv sync`。全部通過時印出 `Forecast View smoke check passed`；任一項未通過時，列出每一項未通過的檢查與實際狀態碼或原因。

`site/` 與 `published/` 上傳前，smoke check 預期會失敗：空的 bucket 讓首頁、`/history` 與兩份 JSON 都回 403，屬上一段所述的預期結果。前端建置產物上傳到 `site/`、地端匯出上傳到 `published/` 之後再執行，結果才有意義。已發布預報的預報時刻距執行當下超過 24 小時也會失敗，表示地端匯出或上傳中斷。

---

## 9. 資源銷毀 (Teardown)

先拆主設定，再拆 bootstrap 層：主設定的 state 存放在 bootstrap 層的 state bucket，它引用的 OIDC provider 也由 bootstrap 層建立。指令都以第 2 節的短期憑證執行。

### 拆除主設定

從 `infra/terraform/` 執行：

1. **刪除地端 access key**：Terraform 不管理 access key，使用者仍有 key 時 `terraform destroy` 無法刪除該使用者。以第 7 節步驟 3 的 `list-access-keys` 列出所有 key，再以步驟 4 的 `delete-access-key` 逐一刪除。

2. **銷毀資源**：

   ```bash
   terraform destroy
   ```

distribution 須先停用才能刪除，`terraform destroy` 會自動停用並等它完成，可能需要數分鐘。`environment` 為 `dev` 以外的值時，bucket 不會強制刪除；須先清空 bucket（含所有舊版本）才能銷毀。

### 拆除 bootstrap 層

從 `infra/terraform/bootstrap/` 執行。state bucket 存放 bootstrap 層自己的 state，因此先把 state 搬回本機，再清空並刪除 bucket。

1. **把 state 搬回本機**：在這個目錄還沒以 S3 backend 初始化過時（例如新的 clone），先執行 `terraform init -backend-config=../state.s3.tfbackend`。接著建立第 3 節步驟 1 的 `backend_override.tf`，再以 `-migrate-state` 初始化，詢問是否複製既有 state 時回答 `yes`：

   ```bash
   cat <<'EOF' > backend_override.tf
   terraform {
     backend "local" {}
   }
   EOF
   terraform init -migrate-state
   ```

2. **清空 state bucket**：bucket 開啟 versioning，須逐一刪除所有物件版本與 delete marker；指定 `--version-id` 是永久刪除：

   ```bash
   BUCKET="$(terraform output -raw state_bucket_name)"
   aws s3api list-object-versions --bucket "$BUCKET" \
       --query '[Versions, DeleteMarkers][][].[Key, VersionId]' --output text |
     while read -r key version; do
       aws s3api delete-object --bucket "$BUCKET" --key "$key" --version-id "$version"
     done
   ```

   再執行一次 `list-object-versions`，應沒有任何輸出。

3. **銷毀資源**：

   ```bash
   terraform destroy
   ```

4. **刪除本機檔案**：

   ```bash
   rm backend_override.tf ../state.s3.tfbackend terraform.tfstate terraform.tfstate.backup
   ```
