# 如何部署 AWS 基礎設施 (Terraform & IAM OIDC)

> [!NOTE]
> **Diátaxis 象限鎖定**
>
> - **目標象限**：How-To Guide
> - **目標讀者**：負責雲端基礎設施部署的 MLOps / DevOps 工程師
> - **核心目標**：指引如何使用 Terraform 建立 AWS 資源並配置 GitHub Actions OIDC 免金鑰部署
> - **排除內容（Avoid）**：AWS 基本概念入門、本機快速預測操作

本指南說明如何透過 Terraform 在 AWS 佈署 S3 Bucket、ECR Repositories、以及 GitHub Actions OIDC 免金鑰認證角色。

---

## 1. 前置準備

- 已安裝 [Terraform](https://developer.hashicorp.com/terraform/downloads) ($\ge 1.5.0$)
- 已配置 AWS CLI 憑證（具備 IAM、S3、ECR 管理權限）
- 已確定目標 GitHub Repository 名稱（例如 `shiro/shiro-mlops`）

---

## 2. 配置 Terraform 變數

切換至 `infra/terraform/` 目錄並建立 `terraform.tfvars`：

```bash
cd infra/terraform
cat <<EOF > terraform.tfvars
aws_region     = "ap-northeast-1"
environment    = "dev"
s3_bucket_name = "shiro-mlops-artifacts-dev"
github_repo    = "shiro/shiro-mlops"
EOF
```

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
   terraform apply -auto-approve
   ```

---

## 4. 取得輸出並設定 GitHub Repository Secrets

執行完成後，Terraform 會輸出以下值：

- `s3_bucket_name`
- `api_ecr_repository_url`
- `dagster_ecr_repository_url`
- `github_actions_role_arn`

前往 GitHub Repository 設置（**Settings > Secrets and variables > Actions**），新增 Repository Variables：

- `AWS_REGION`: `ap-northeast-1`
- `AWS_ROLE_TO_ASSUME`: `<github_actions_role_arn 輸出值>`
- `S3_BUCKET_NAME`: `<s3_bucket_name 輸出值>`

---

## 5. 資源銷毀 (Teardown)

若要清理雲端實驗資源以避免產生額外費用：

```bash
terraform destroy -auto-approve
```
