# ADR-0016：儲存庫改為公開，不升級付費方案

> - Created: 2026-11-22
> - Last Updated: 2026-11-22
> - Author: Bo-Xue Huang
> - Status: 已接受
> - Related: [ADR-0015](0015-publish-forecast-view-as-static-precomputed-output.md)、[GitHub Rulesets](../reference/github-rulesets.md)、[GitHub 儲存庫設定](../reference/github-repository-settings.md)、[Terraform state 與部署權責](../reference/terraform-state-and-deployment.md)

---

## 1. Context

儲存庫所在的帳號使用 GitHub Free 方案，這個方案對 private 儲存庫有兩個限制：

- **Actions 分鐘數**：private 儲存庫每月只有 2,000 分鐘。每個 PR 會跑 6 個平行 job，其中 `nginx` 與 `backend` 會建置 Docker 映像檔。到 2026-11-22 為止，共有 426 次 workflow run，額度不夠用。public 儲存庫使用標準 runner 不計分鐘數。
- **Rulesets**：Free 方案只在 public 儲存庫強制執行 repository rules。`.github/rulesets/` 的三份 ruleset 雖然設為 `active`，在 private 時並沒有擋下任何操作。

公開前稽核了完整歷史，範圍是 853 個 commit，包含所有分支、tag 與 PR head（`refs/pull/*`）。稽核結果：

- **沒有機密**：沒有機密值、AWS 金鑰、Terraform state、`.env`，也沒有真實的帳號 ID。
- **AWS 一律走 OIDC**：workflow 從第一版起就以 OIDC 取得 AWS 角色，從未上傳 artifact。
- **舊 log 沒碰過 AWS**：Terraform job 加入後沒有執行過，因此舊的 Actions log 不含 AWS 資訊。
- **有個人資訊**：commit 作者的個人 email、維護者的姓名、另一個 GitHub 帳號名，以及舊文件中的本機路徑。

## 2. Decision

儲存庫改為 public，同時決定以下各點。

### 2.1 歷史與個人資訊

- **不改寫歷史**：歷史照現狀公開。GitHub 會保留每個 PR 的 `refs/pull/<n>/head`，改寫歷史也清不掉舊 commit，而且需要 force push，會與 `non_fast_forward` 規則衝突。
- **之後不再外洩 email**：之後的 commit 一律使用 GitHub noreply email，帳號另外開啟「Block command line pushes that expose my email」。
- **著作人姓名**：LICENSE、`pyproject.toml` 與 ADR 都使用維護者的姓名 Bo-Xue Huang。

### 2.2 授權與貢獻

- **程式碼授權**：程式碼以 MIT 授權發布。
- **資料授權**：台電與氣象署的資料集依「政府資料開放授權條款-第1版」使用。這份授權不受 MIT 涵蓋，README 依條款附件的顯名聲明標示來源。預報檢視上的標示由 [GitHub #282](https://github.com/shiroki9979/shiro-mlops/issues/282) 處理。
- **不接受外部 PR**：fork 開的 PR 一律要維護者核准後才執行 workflow。`docs/agents/issue-tracker.md` 的「PRs as a request surface」維持 `no`。

### 2.3 公開後的設計限制

之後修改 workflow 與 GitHub 設定時，必須遵守以下限制：

- **不用自架 runner**：任何人都能開 PR，自架 runner 等於讓外人在自己的機器上執行任意程式碼。
- **沒有 push ruleset**：private 改為 public 時，GitHub 會停用所有 push ruleset。大檔與受限副檔名改由 `scripts/check_conventions.py blob-limits` 在 PR 擋下（[GitHub #261](https://github.com/shiroki9979/shiro-mlops/issues/261)），這項檢查在 `lint-and-test` job 中執行，而 `lint-and-test` 是必要檢查。
- **Actions log 與 job summary 人人可讀**：
  - 機密只放 Actions secrets。
  - repository variables 的值在 log 中不會被遮蔽，必須當作公開資訊處理，包括角色 ARN、state bucket 名稱，以及其中的 AWS 帳號 ID。
- **workflow 必須假設會有 fork PR**：
  - 不得以 `pull_request_target` 或 `workflow_run` 執行未信任的程式碼。
  - fork PR 拿不到 secrets，也拿不到 `id-token: write`，因此 plan 角色的 `sub` 雖然是 `repo:shiroki9979/shiro-mlops:pull_request`，只有本儲存庫分支開的 PR 能 assume。

### Rationale & Alternatives Considered

- **升級 GitHub Pro**：rulesets 會在 private 生效，分鐘數也會增加。但要按月付費，分鐘數仍有上限，而專案沒有必須保密的程式碼。不採用。
- **另開只含單一 commit 的新儲存庫**：可以避開舊歷史裡的個人資訊，代價是 PR、issue 與審查紀錄都留在舊儲存庫，文件中上百個 issue 連結在公開讀者眼中也會失效。歷史裡的個人資訊都是維護者願意公開的姓名與帳號，不值得付出這個代價。不採用。
- **自架 runner**：public 儲存庫不能用（見 §2.3）。若留在 private 改用自架 runner，又要自己維護機器。不採用。
- **把 AWS 識別資訊改放進 secrets**：可以讓帳號 ID 不出現在 log，但要修改 `ci.yml` 與兩份部署文件。AWS 不把帳號 ID 視為機密，OIDC 信任條件也已綁定 `sub`，只換來隱藏一個不算機密的值，不划算。不採用。

## 3. Consequences

- **Actions 免費**：標準 runner 的 Actions 分鐘數不再受額度限制。
- **rulesets 開始強制**：所有變更都必須走 PR，包括過去直接推到 `dev` 的文件修改。
- **帳號 ID 出現在公開 log**：從第一次 release PR 的 `terraform-plan` 起，AWS 帳號 ID 與 bucket 名稱會出現在公開 log 中。這一點已接受。
- **安全功能免費**：secret scanning、push protection 與 CodeQL 在 public 儲存庫都免費，設定見[GitHub 儲存庫設定](../reference/github-repository-settings.md)。
- **公開無法收回**：改回 private 也收不回已公開的內容，fork、clone 與快取都會留著。

## 4. Compliance

- **CI**：`lint-and-test` 對 PR 範圍內每個 commit 執行 `blob-limits`。
- **Code Review 清單**：
  - 不得新增自架 runner。
  - 不得以 `pull_request_target` 或 `workflow_run` 執行未信任的程式碼。
  - 機密不得放進 repository variables，也不得印到 log。
- **設定對照**：GitHub 上的設定與[GitHub 儲存庫設定](../reference/github-repository-settings.md)保持一致。

## 5. Notes

- 決策經 2026-11-22 的設計訪談定案。公開與設定的人工步驟追蹤於 [GitHub #281](https://github.com/shiroki9979/shiro-mlops/issues/281)。
- GitHub 方案與公開後行為的事實取自 GitHub 定價頁與 GitHub 官方文件，包括 repository visibility、fork PR 的 secrets 與 `GITHUB_TOKEN` 權限、自架 runner 的安全建議。查閱日期為 2026-11-22。
