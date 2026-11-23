# GitHub 儲存庫設定

- 建立日期：2026-11-22
- 最後更新：2026-11-23
- 專案版本：`0.4.0`

---

本文件記錄 rulesets 以外、要在 GitHub 上手動維持的儲存庫設定，包括可見性、Actions 對 fork PR 的處理、安全功能，以及維護者帳號的 email 設定。改為公開的決策與它帶來的設計限制見 [ADR-0016](../adr/0016-make-repository-public.md)，branch 與 tag 的規則見 [GitHub Rulesets](github-rulesets.md)。

這些設定只存在於 GitHub，本文件是它們的副本。兩者不一致時，GitHub 上的設定才是生效版本：先確認哪一邊是對的，再修正另一邊。

## 1. 可見性

| 設定 | 值 | 位置 |
| :--- | :--- | :--- |
| Repository visibility | Public | **Settings → General → Danger Zone** |

依 GitHub 文件，private 改為 public 後會有以下變化：

- 任何人都能讀取程式碼、全部歷史，以及 Actions 的歷史紀錄與 log。
- 任何人都能 fork。
- 所有 push ruleset 都會被停用，替代做法見 [GitHub Rulesets](github-rulesets.md)。
- Free 方案的 branch 與 tag rulesets 只在 public 儲存庫強制執行，改為 public 後才真正生效。

## 2. Actions

| 設定 | 值 | 位置 | 原因 |
| :--- | :--- | :--- | :--- |
| Approval for running fork pull request workflows from contributors | Require approval for all external contributors | **Settings → Actions → General** | 不接受外部 PR（[README](../../README.md#contributing)）。任何外部 PR 的 workflow 都要等維護者看過 diff 再執行，未審查的程式碼不會在 runner 上執行 |

fork PR 的 workflow 執行時：

- 除了 `GITHUB_TOKEN`，拿不到任何 secret。
- 只能得到唯讀權限，`id-token: write` 不會生效，因此無法 assume 任何 AWS 角色（[Terraform state 與部署權責 §3](terraform-state-and-deployment.md#3-角色的信任與權限)）。

`.github/workflows/` 不使用自架 runner，也不以 `pull_request_target` 或 `workflow_run` 執行未信任的程式碼（[ADR-0016 §2.3](../adr/0016-make-repository-public.md#23-公開後的設計限制)）。

## 3. 安全功能

位置在 **Settings → Advanced Security**，舊介面叫 **Code security**。下表依該頁由上到下的順序排列，方便逐項對照。

| 區塊 | 功能 | 狀態 | 說明 |
| :--- | :--- | :--- | :--- |
| — | Private vulnerability reporting | 開啟 | 讓回報者以 **Security → Report a vulnerability** 私下回報 |
| Dependency Scanning | Dependency graph | 開啟 | Dependabot alerts 需要它 |
| Dependency Scanning | Automatic dependency submission | Disabled | 只適用於建置時才算得出依賴的生態系；`uv.lock` 與 `pnpm-lock.yaml` 可直接讀取 |
| Dependabot | Dependabot alerts | 開啟 | 依賴項有已知漏洞時發出 alert |
| Dependabot | Malware alerts | 關閉 | 依賴項是已知惡意套件時發出 alert；要開時直接切換即可 |
| Dependabot | Dependabot auto-triage rules | GitHub 預設規則（1 條） | 未自訂規則 |
| Dependabot | Dependabot security updates | 關閉 | 單人維護的儲存庫只看 alert，再由人決定是否升級 |
| Dependabot | Grouped security updates | 關閉 | 只在開啟 security updates 時有作用 |
| Dependabot | Dependabot version updates | 關閉 | 沒有 `.github/dependabot.yml`，避免大量更新 PR |
| Code Security | CodeQL analysis | Default setup | 語言由 GitHub 自動偵測；結果不列入 rulesets 的必要檢查 |
| AI Scan | AI Scan for repositories、AI Scan for pull requests、Scan for AI applications | 關閉 | 會消耗 AI credits |
| AI Scan | Copilot Autofix | 開啟 | 只在 CodeQL alert 中附上修正建議，不會自己開 PR |
| AI Scan | Agentic autofix | 關閉 | 會消耗 AI credits，並會自動開 PR |
| Protection rules | Check runs failure threshold | 預設：Security alert severity level **High or higher**，Standard alert severity level **Only errors** | CodeQL 不在必要檢查內，這個門檻不會擋下合併 |
| Secret Protection | Secret scanning | 開啟 | 掃描整個歷史與之後的推送，發現已知格式的機密時發出 alert |
| Secret Protection | Push protection | 開啟 | 推送內容含已知格式的機密時直接拒絕 |

## 4. 維護者帳號

commit email 不隱藏（[ADR-0016 §2.1](../adr/0016-make-repository-public.md#21-歷史與個人資訊)）：

- **不要求 noreply 地址**：本機 git 的 `user.email` 不要求改用 GitHub noreply 地址。用個人 email 做的 commit，推上去後就隨歷史公開。
- **email 隱私設定不在本文件管理範圍**：**Settings → Emails** 的 **Keep my email addresses private** 與 **Block command line pushes that expose my email** 屬於維護者個人帳號，本文件不規定它們要開或關。

要改為隱藏時，把 `user.email` 設成 `92085403+shiroki9979@users.noreply.github.com`，並勾選上面兩個選項，同時更新本節與 ADR-0016 §2.1。

## 5. 維護方式

1. 在 GitHub 上修改設定。
2. 在同一個 PR 中更新本文件；改變的若是 ADR-0016 的設計限制，也一併更新 ADR。
