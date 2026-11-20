# 如何部署 AWS 基礎設施 (Terraform & IAM OIDC)

- 建立日期：2026-08-23
- 最後更新：2026-11-20

> [!NOTE]
> **Diátaxis 象限鎖定**
>
> - **目標象限**：How-To Guide
> - **目標讀者**：負責雲端基礎設施部署的 MLOps / DevOps 工程師
> - **核心目標**：指引如何使用 Terraform 建立預報檢視的靜態託管資源、配置 GitHub Actions OIDC，並建立與輪替地端上傳用 access key
> - **排除內容（Avoid）**：AWS 基本概念入門、本機快速預測操作、CloudFront 與 CD 管線設定

依 [ADR-0015](../adr/0015-publish-forecast-view-as-static-precomputed-output.md)，雲端只存放並提供預報檢視的發布產物。本指南說明如何透過 Terraform 建立下列資源：

- S3 bucket `shiro-mlops-forecast-view`：`site/` 放前端建置產物、`published/` 放匯出的 JSON（配置見[預報檢視的雲端託管 §1](../reference/forecast-view-hosting.md#1-s3-配置與寫入權限)）；保留 versioning，舊版本 30 天後過期。
- GitHub Actions OIDC provider 與 CI 角色：只能寫入 `site/*`。
- 地端上傳用 IAM 使用者 `shiro-mlops-onprem-publisher`：只能 `PutObject` 到 `published/*`。
- AWS Budgets：月實際支出達 5 美元、預測支出達 10 美元時寄 email 警示。

CloudFront 由 TICKET-412 另行處理；Terraform state 與 apply 權責待 [GitHub #129](https://github.com/shiroki9979/shiro-mlops/issues/129) 定案。

---

## 1. 前置準備

- 已安裝 [Terraform](https://developer.hashicorp.com/terraform/downloads) ($\ge 1.5.0$)
- 已配置 AWS CLI 憑證（具備 IAM、S3、Budgets 管理權限）
- 已確定目標 GitHub Repository 名稱（例如 `shiro/shiro-mlops`）
- 已確定接收成本警示的 email 地址

---

## 2. 配置 Terraform 變數

切換至 `infra/terraform/` 目錄並建立 `terraform.tfvars`：

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
- `github_actions_role_arn`
- `onprem_publisher_user_name`

前往 GitHub Repository 設置（**Settings > Secrets and variables > Actions**），新增 Repository Variables：

- `AWS_ROLE_TO_ASSUME`: `<github_actions_role_arn 輸出值>`

---

## 5. 建立地端上傳用 access key

access key 不由 Terraform 產生或輸出，避免 secret 進入 Terraform state。以具備 IAM 管理權限的 AWS CLI 憑證建立：

```bash
aws iam create-access-key \
  --user-name "$(terraform output -raw onprem_publisher_user_name)"
```

把回傳的 `AccessKeyId` 與 `SecretAccessKey` 寫入地端主機的 `.env`（勿提交）：

```dotenv
AWS_ACCESS_KEY_ID=<AccessKeyId>
AWS_SECRET_ACCESS_KEY=<SecretAccessKey>
AWS_DEFAULT_REGION=ap-northeast-1
```

確認 key 只能寫入 `published/`（第一個指令應成功，第二個應回 `AccessDenied`）：

```bash
echo '{}' > /tmp/probe.json
aws s3 cp /tmp/probe.json s3://shiro-mlops-forecast-view/published/probe.json
aws s3 cp /tmp/probe.json s3://shiro-mlops-forecast-view/site/probe.json
```

這把 key 也不能刪除物件，`published/probe.json` 需以管理員憑證刪除。

---

## 6. 輪替地端 access key

IAM 使用者最多同時有兩把 access key，輪替時先建新 key、確認可用後再停用舊 key：

1. **建立新 key**：

   ```bash
   aws iam create-access-key --user-name shiro-mlops-onprem-publisher
   ```

2. **更新地端 `.env`**：換上新的 `AWS_ACCESS_KEY_ID` 與 `AWS_SECRET_ACCESS_KEY`，重新啟動執行匯出的地端服務，確認下一次每小時匯出成功上傳（地端 Dagster 執行紀錄無錯誤）。

3. **停用舊 key**：

   ```bash
   aws iam list-access-keys --user-name shiro-mlops-onprem-publisher
   aws iam update-access-key --user-name shiro-mlops-onprem-publisher \
     --access-key-id <舊 AccessKeyId> --status Inactive
   ```

4. **刪除舊 key**：觀察一段時間確認沒有服務仍使用舊 key 後刪除：

   ```bash
   aws iam delete-access-key --user-name shiro-mlops-onprem-publisher \
     --access-key-id <舊 AccessKeyId>
   ```

懷疑 key 外洩時，直接停用並刪除外洩的 key，再依第 5 節建立新 key。外洩的 key 最多能竄改 `published/` 下的 JSON，可從 S3 舊版本（保留 30 天）復原，並由下一次匯出覆寫。

---

## 7. 資源銷毀 (Teardown)

若要清理雲端資源以避免產生額外費用，先刪除地端上傳用 IAM 使用者的 access key（Terraform 不管理它，留著會讓 `terraform destroy` 無法刪除該使用者）：

```bash
aws iam list-access-keys --user-name shiro-mlops-onprem-publisher
aws iam delete-access-key --user-name shiro-mlops-onprem-publisher \
  --access-key-id <AccessKeyId>
terraform destroy
```

`environment` 為 `dev` 以外的值時，bucket 不會強制刪除；須先清空 bucket（含所有舊版本）才能銷毀。
