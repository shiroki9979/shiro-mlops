# GitHub Rulesets

- 建立日期：2026-11-22
- 最後更新：2026-11-22
- 專案版本：`0.4.0`

---

本文件記錄儲存庫在 GitHub 上設定的 Rulesets：保護哪些分支與標籤、合併前要通過哪些檢查，以及哪些角色可以繞過規則。各 ruleset 的完整設定以 GitHub 匯出的 JSON 存放在 `.github/rulesets/`，JSON 是實際設定的副本，GitHub 上的設定才是生效的版本。範圍與完成標準見 [GitHub #145](https://github.com/shiroki9979/shiro-mlops/issues/145)。

## 1. 總覽

| Ruleset | 對象 | 保護的 ref | JSON |
| :--- | :--- | :--- | :--- |
| `protect-dev` | 分支 | `dev`、`main` | [`.github/rulesets/protect-dev.json`](../../.github/rulesets/protect-dev.json) |
| `protect-release-tags` | 標籤 | `v*` | [`.github/rulesets/protect-release-tags.json`](../../.github/rulesets/protect-release-tags.json) |

尚未建立限制檔案大小與副檔名的 Push Ruleset（#145 範圍第 3 項）。

## 2. `protect-dev`：整合分支與發布分支

`dev` 是預設分支與整合分支，`main` 只接收 `dev` 的 release PR（分支流程見 [issue-tracker.md](../agents/issue-tracker.md#branches)）。兩者套用同一組規則：

| 規則 | 設定 | 效果 |
| :--- | :--- | :--- |
| `deletion` | — | 不能刪除分支 |
| `non_fast_forward` | — | 不能強制推送 |
| `pull_request` | 核准數 `0` | 必須透過 PR 合併；不要求審查者核准，因為單人儲存庫無法核准自己的 PR |
| `pull_request` | `required_review_thread_resolution: true` | 所有審查對話都標為已解決後才能合併 |
| `pull_request` | `allowed_merge_methods: merge, squash, rebase` | 三種合併方式都允許；`dev` → `main` 的 release PR 應使用 merge commit，否則兩個分支的歷史會分岔 |
| `required_status_checks` | `strict_required_status_checks_policy: false` | 合併前必須通過下表的檢查，但不要求 PR 分支先與目標分支同步 |

### 2.1 必要檢查

必要檢查以 GitHub Actions（`integration_id: 15368`）回報的 job 名稱比對。重新命名下列 job 時，必須在同一個 PR 中更新 ruleset，否則 PR 會一直等待一個不會出現的檢查。

| 檢查 | Workflow | 內容 |
| :--- | :--- | :--- |
| `lint-and-test` | `.github/workflows/ci.yml` | Ruff lint 與 format、儲存庫慣例檢查、`tests/` 與 `lab/tests` 的 pytest |
| `frontend` | `.github/workflows/ci.yml` | 前端 lint、測試、建置，以及預報檢視 bundle 檢查 |
| `nginx` | `.github/workflows/ci.yml` | 建置 nginx 映像檔，smoke test 兩個前端應用與 API gateway |
| `docs` | `.github/workflows/ci.yml` | Markdown lint、離線檢查相對連結與錨點、用詞與文件日期檢查、註解種類檢查 |
| `pr-base-branch` | `.github/workflows/branch-flow.yml` | 進入 `main` 的 PR 的 head 必須是 `dev` |

`ci.yml` 中不在必要檢查內的 job：

| Job | 執行時機 | 不通過時 |
| :--- | :--- | :--- |
| `backend` | 每個 PR 與推送 | 不阻擋合併；推送到 `main` 時 `deploy` 需要它，失敗即不部署 |
| `infra` | 每個 PR 與推送 | 不阻擋合併；推送到 `main` 時 `deploy` 需要它，失敗即不部署 |
| `terraform-plan` | 只在進入 `main` 的 PR | 不阻擋合併；只供審查雲端變更 |
| `deploy` | 只在推送到 `main` | 合併後才執行，不屬於合併門禁 |

## 3. `protect-release-tags`：發布標籤

發布標籤（`v0.4.0` 等）由人在 release PR 合併後手動建立。規則只禁止改動已存在的標籤，不限制建立新標籤：

| 規則 | 效果 |
| :--- | :--- |
| `deletion` | 不能刪除標籤 |
| `non_fast_forward` | 不能強制推送標籤 |
| `update` | 已存在的標籤不能改指向其他 commit |

這個 ruleset 沒有 bypass 角色：儲存庫只有一位管理員，若讓管理員繞過，規則就形同虛設。標籤打錯時，先在 GitHub 把這個 ruleset 的 enforcement 暫時改為 `disabled`，修正標籤後立即改回 `active`。

## 4. Bypass 例外清單

| Ruleset | 角色 | `actor_id` | 模式 | 可以做什麼 |
| :--- | :--- | :--- | :--- | :--- |
| `protect-dev` | Repository role：Admin | `5` | `pull_request` | 在 PR 上繞過規則（例如檢查未通過仍合併）；直接推送仍受規則限制 |
| `protect-release-tags` | 無 | — | — | — |

## 5. 維護方式

1. 在 GitHub 的 **Settings → Rules → Rulesets** 修改設定。
2. 從同一頁的 ruleset 選單匯出 JSON，覆蓋 `.github/rulesets/` 中對應的檔案。
3. 在同一個 PR 中更新本文件。

新建 ruleset 時，可在 **New ruleset → Import a ruleset** 匯入 `.github/rulesets/` 中的 JSON。尚未建立的 ruleset，其 JSON 沒有 `id` 與 `source` 欄位；建立後重新匯出即會補上。
