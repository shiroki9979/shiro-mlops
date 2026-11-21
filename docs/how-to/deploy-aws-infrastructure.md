# 如何部署 AWS 基礎設施 (Terraform & IAM OIDC)

- 建立日期：2026-08-23
- 最後更新：2026-11-21

> [!NOTE]
> **Diátaxis 象限鎖定**
>
> - **目標象限**：How-To Guide
> - **目標讀者**：負責雲端基礎設施部署的 MLOps / DevOps 工程師
> - **核心目標**：指引如何使用 Terraform 建立預報檢視的靜態託管資源（S3 與 CloudFront）、配置 GitHub Actions OIDC、建立與輪替地端上傳用 access key，並取得預報檢視的網址與執行雲端 smoke check
> - **排除內容（Avoid）**：AWS 基本概念入門、本機快速預測操作、CD 管線設定

依 [ADR-0015](../adr/0015-publish-forecast-view-as-static-precomputed-output.md)，雲端只存放並提供預報檢視的發布產物。本指南說明如何透過 Terraform 建立下列資源：

- S3 bucket（名稱取自變數 `s3_bucket_name`）：`site/` 放前端建置產物、`published/` 放匯出的 JSON（配置見[預報檢視的雲端託管 §1](../reference/forecast-view-hosting.md#1-s3-配置與寫入權限)）；保留 versioning，舊版本 30 天後過期。
- GitHub Actions OIDC provider 與 CI 角色：只能寫入 `site/*`。
- 地端上傳用 IAM 使用者（名稱見輸出 `onprem_publisher_user_name`）：只能 `PutObject` 到 `published/*`。
- CloudFront distribution：經 Origin Access Control（OAC）讀取 bucket 的 `site/` 與 `published/`，含 SPA 改寫函式 `spa-rewrite` 與各 behavior 的 cache policy（配置見[預報檢視的雲端託管 §2](../reference/forecast-view-hosting.md#2-origin-與-behavior)、[§3](../reference/forecast-view-hosting.md#3-distribution-其他設定)）；bucket policy 只授權這個 distribution 讀取這兩個 prefix。
- AWS Budgets：月實際支出達 5 美元、預測支出達 10 美元時寄 email 警示。

Terraform state 與 apply 權責待 [GitHub #129](https://github.com/shiroki9979/shiro-mlops/issues/129) 定案。

除第 2 節的 `cd` 外，本指南的指令都從 `infra/terraform/` 目錄執行：bucket、使用者與 region 一律以 `terraform output` 從該目錄的 state 取值，不另行手寫。

---

## 1. 前置準備

- 已安裝 [Terraform](https://developer.hashicorp.com/terraform/downloads) ($\ge 1.5.0$)
- 已配置 AWS CLI 管理員憑證（具備 IAM、S3、CloudFront、Budgets 管理權限）；除第 5 節的權限確認外，指令都以這組憑證執行
- 已確定目標 GitHub Repository 名稱（例如 `shiro/shiro-mlops`）
- 已確定接收成本警示的 email 地址

---

## 2. 配置 Terraform 變數

從 repository 根目錄切換至 `infra/terraform/` 並建立 `terraform.tfvars`：

```bash
cd infra/terraform
cat <<EOF > terraform.tfvars
aws_region         = "ap-northeast-1"
environment        = "dev"
s3_bucket_name     = "shiro-mlops-forecast-view"
github_repo        = "shiro/shiro-mlops"
budget_alert_email = "ops@example.com"
EOF
```

`budget_alert_email` 沒有預設值，必須提供。

---

## 3. 執行 Terraform 部署

1. **初始化工作目錄**：

   ```bash
   terraform init
   ```

2. **預覽變更**：

   ```bash
   terraform plan
   ```

3. **套用資源**：

   ```bash
   terraform apply
   ```

---

## 4. 取得輸出並設定 GitHub Repository Variables

執行完成後，Terraform 會輸出以下值：

- `s3_bucket_name`
- `aws_region`
- `github_actions_role_arn`
- `onprem_publisher_user_name`
- `forecast_view_url`
- `cloudfront_distribution_id`

前往 GitHub Repository 設置（**Settings > Secrets and variables > Actions**），新增 Repository Variables：

- `AWS_ROLE_TO_ASSUME`: `<github_actions_role_arn 輸出值>`

---

## 5. 建立地端上傳用 access key

access key 由人工建立與輪替，不經 Terraform（見 [ADR-0015 §2.3](../adr/0015-publish-forecast-view-as-static-precomputed-output.md#23-地端到雲端的匯出)）。以管理員憑證建立：

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

`published/` 會公開提供，且這把 key 不能刪除物件。確認後以管理員憑證逐一刪除 `published/probe.json` 的所有版本；指定 `--version-id` 是永久刪除，不會留下 delete marker：

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

## 6. 輪替地端 access key

IAM 使用者最多同時有兩把 access key，輪替時先建新 key、確認可用後再停用舊 key：

1. **建立新 key**：以第 5 節的 `create-access-key` 指令建立。

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

懷疑 key 外洩時，依步驟 3、4 直接停用並刪除外洩的 key，再依第 5 節建立新 key。外洩的影響範圍與復原方式見 [ADR-0015 §2.3](../adr/0015-publish-forecast-view-as-static-precomputed-output.md#23-地端到雲端的匯出)。

---

## 7. 取得預報檢視網址

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

bucket 剛建立時 `site/` 與 `published/` 都是空的。CloudFront 沒有列出 bucket 的權限，缺檔一律回 403，屬預期結果，不是設定錯誤：

- `site/` 還沒上傳前，首頁 `/` 與 `/history` 回 403。
- `published/` 還沒上傳前，`/published/` 下的 JSON 回 403；第 5 節的地端匯出上傳後，約一分鐘內生效。

### 執行雲端 smoke check

以 `forecast_view_url` 的值，透過 repo 根目錄的 Makefile target 驗證網址符合[預報檢視的雲端託管 §5](../reference/forecast-view-hosting.md#5-部署與驗證)：

```bash
make -C ../.. cloud-smoke ARGS="--base-url $(terraform output -raw forecast_view_url)"
```

腳本只用 Python 標準函式庫，不需先執行 `uv sync`。全部通過時印出 `Forecast View smoke check passed`；任一項未通過時，列出每一項未通過的檢查與實際狀態碼或原因。

`site/` 與 `published/` 上傳前，smoke check 預期會失敗：空的 bucket 讓首頁、`/history` 與兩份 JSON 都回 403，屬上一段所述的預期結果。前端建置產物上傳到 `site/`、地端匯出上傳到 `published/` 之後再執行，結果才有意義。已發布預報的預報時刻距執行當下超過 24 小時也會失敗，表示地端匯出或上傳中斷。

---

## 8. 資源銷毀 (Teardown)

1. **刪除地端 access key**：Terraform 不管理 access key，使用者仍有 key 時 `terraform destroy` 無法刪除該使用者。以第 6 節步驟 3 的 `list-access-keys` 列出所有 key，再以步驟 4 的 `delete-access-key` 逐一刪除。

2. **銷毀資源**：

   ```bash
   terraform destroy
   ```

distribution 須先停用才能刪除，`terraform destroy` 會自動停用並等它完成，可能需要數分鐘。`environment` 為 `dev` 以外的值時，bucket 不會強制刪除；須先清空 bucket（含所有舊版本）才能銷毀。
