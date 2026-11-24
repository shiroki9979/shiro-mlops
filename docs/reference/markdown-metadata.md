# Markdown 文件 metadata

> - Created: 2026-11-24
> - Last Updated: 2026-11-24
> - Related: [ADR-0016](../adr/0016-make-repository-public.md)、[GitHub #389](https://github.com/shiroki9979/shiro-mlops/issues/389)

本文件規定 repo 內 Markdown 文件檔頭的格式：第一行的 H1、緊接其後的 metadata 區塊、允許的 key 與值，以及檔頭不得出現的內容。格式由 `scripts/check_conventions.py doc-metadata` 檢查，日期是否隨內容更新由 `doc-dates` 檢查，兩者都只在 CI 執行，不依賴本機 hook（公開 repo 的 fork PR 不會安裝 hook，見 [ADR-0016](../adr/0016-make-repository-public.md)）。

metadata 只記錄文件「現在是什麼」；變更經過交給 git 的 commit message，ADR 的修訂註記寫在 `Notes`（見[第 6 節](#6-adr-的取代與修訂註記)）。

## 1. 範圍與文件類型

- **範圍**：所有已追蹤的 `.md`，排除 `lab/`、`data/`，以及任何層級的 `.venv`、`node_modules`。`doc-metadata` 與 `doc-dates` 共用這份範圍定義（`is_doc_in_scope`），兩項檢查涵蓋的文件集合相同。`lab/` 的研究報告依 [lab 契約](lab.md) 撰寫，不受本規範檢查。
- **文件類型只看路徑**：
  - ADR：`docs/adr/` 下的 `NNNN-*.md`。
  - 一般文件：其餘所有文件，README 一律算一般文件。
- 不設 spec 類型，也不設 `Decision` key。

## 2. 檔頭格式

```markdown
# 文件標題

> - Created: 2026-11-24
> - Last Updated: 2026-11-24
> - Related: [ADR-0016](../adr/0016-make-repository-public.md)

導言（選填）。

## 1. 第一節
```

- 第一行必須是 H1（`# 標題`）。`markdownlint-disable` 之類的 directive 放在 metadata 區塊之後。
- H1 之後的第一個非空區塊必須是 metadata 區塊：連續的 blockquote 行，每行一個 `> - Key: value`。
- key 與值之間用半形冒號加一個空白，不接受全形冒號 `：`，key 不加粗體。
- metadata 區塊之後到第一個 H2 之間可以寫導言。

## 3. Key

依下表順序排列，每個 key 最多出現一次：

| Key | 適用 | 必填 | 值 |
| :--- | :--- | :--- | :--- |
| `Created` | 全部 | 是 | 單一 `YYYY-MM-DD` |
| `Last Updated` | 全部 | 是 | 單一 `YYYY-MM-DD`，不得早於 `Created` |
| `Author` | 全部 | 否 | 自由文字 |
| `Status` | 全部 | ADR 必填；一般文件選填 | 見第 4 節 |
| `Related` | 全部 | 否 | 只放連結 |
| `Supersedes` | ADR | 否 | 只放連結 |
| `Superseded by` | ADR | 否 | 只放連結 |
| `Revisions` | ADR | 否 | 一個指向本檔 `Notes` H2 的同檔錨點 |

- key 大小寫須與上表一致（`Last updated` 不是允許的 key）。
- 日期後面不接說明文字；說明寫進正文。
- **只放連結**：一個或多個 `[text](target)`，多個連結以 `、` 串接，不夾其他文字。連結的說明寫進正文。
- **`Revisions`**：寫成 `[Notes](#notes)` 或 `[Notes](#5-notes)`，錨點須是本檔標題為 `Notes` 的 H2。H2 的章號（例如 `5.`）可有可無，判定時忽略。

## 4. `Status`

ADR 的 `Status` 必填，值為下列之一：

| 值 | 意義 |
| :--- | :--- |
| `Proposed` | 提出中，尚未決定 |
| `Accepted` | 已接受，整份 ADR 仍然有效 |
| `Superseded` | 整份 ADR 已被其他 ADR 取代，同時以 `Superseded by` 連到取代它的 ADR |
| `Deprecated` | 不再適用，也沒有取代它的 ADR |
| `Rejected` | 提出後未被採用 |

一般文件的 `Status` 選填，值為下列之一：

| 值 | 意義 |
| :--- | :--- |
| （不設） | 文件描述現況。reference、tutorial、how-to 預設不設 |
| `Open` | 紀錄類文件（architecture review、research）仍在進行 |
| `Closed` | 紀錄類文件已結案 |
| `Obsolete` | 文件不再適用，例如已完成且不會再執行的一次性操作 |

仍對部分環境有效的一次性操作（例如對舊資料庫的升級步驟）不設 `Status`。

## 5. 檔頭禁止事項

檔頭指 H1 到第一個 H2 之間的內容，metadata 區塊除外。

- 去掉行首的 `>`、`-`、`**` 後，以 `YYYY-MM-DD` 日期或「修訂」開頭的行違規。變更紀錄寫在 commit message，ADR 的修訂註記寫在 `Notes`。
- 第 3 節的 key，或下列舊 key，出現在 metadata 區塊外違規：`建立日期`、`最後更新`、`狀態`、`專案版本`、`目標象限`、`目標讀者`、`核心目標`、`排除內容`、`文件類型`、`檢視基準`、`前次檢視`、`對應`、`結論`。舊 key 後面的括號說明（例如 `排除內容（Avoid）`）不影響判定。
- 其他文字不檢查。導言裡的 `- **詞**（說明）：內容` 清單不算 key。
- 版本號只寫在套件設定，不寫進文件檔頭。

## 6. ADR 的取代與修訂註記

- 整份 ADR 被取代：`Status` 改為 `Superseded`，並以 `Superseded by` 連到新的 ADR；新的 ADR 以 `Supersedes` 連回。
- 部分被取代：維持原本的 `Status`，加上 `Superseded by`，並在 `Notes` 寫一條修訂註記說明哪一段不再適用。
- 修訂註記一律寫在標題為 `Notes` 的 H2 下，`Revisions` 指向這一節。能直接改正文就不寫修訂註記；註記的寫法由審查者判斷，見 [CODING_STANDARDS.md](../../CODING_STANDARDS.md#文件)。

## 7. 日期

- `Last Updated` 不得早於 PR 範圍內碰到該檔的非 merge commit 中，最新的 author date（以作者時區計）。不要求是當天，跨好幾天的 PR 不必每天更新。
- 只改 metadata 區塊的 commit（補 `Related`、改 `Status`）與純改名、搬移的 commit 不計入；改名的同時修改正文仍計入。舊格式檔頭轉為本格式也算只改 metadata。
- 新增的文件，`Created` 不得早於新增它的 commit 的 author date。複製舊文件當範本時，要改成新增當天的日期。

## 8. 規則代號

`doc-metadata` 的每則違規以 `檔案:行號: 規則代號: 說明` 印出，說明附允許的值。

| 規則代號 | 違規情形 |
| :--- | :--- |
| `not-utf8` | 檔案不是 UTF-8 編碼 |
| `h1-first-line` | 第一行不是 H1 |
| `metadata-block-position` | H1 之後的第一個區塊不是 metadata 區塊 |
| `metadata-item` | metadata 區塊中的行不是 `> - Key: value`，例如用了全形冒號或沒有值 |
| `missing-key` | 缺少必填 key：全部文件的 `Created`、`Last Updated`，以及 ADR 的 `Status` |
| `unknown-key` | key 不在第 3 節的表中 |
| `key-not-applicable` | 一般文件使用了只適用 ADR 的 `Supersedes`、`Superseded by`、`Revisions` |
| `duplicate-key` | 同一個 key 出現兩次 |
| `key-order` | key 未依第 3 節的順序排列 |
| `invalid-date` | 日期不是單一、有效的 `YYYY-MM-DD` |
| `date-order` | `Last Updated` 早於 `Created` |
| `status-value` | `Status` 不在該文件類型允許的值之中 |
| `link-only` | `Related`、`Supersedes`、`Superseded by` 夾了連結以外的文字，或未以 `、` 串接 |
| `revisions-target` | `Revisions` 不是指向本檔 `Notes` H2 的同檔錨點 |
| `header-dated-line` | 檔頭有以日期或「修訂」開頭的行 |
| `header-stray-key` | 第 3 節的 key 或舊 key 出現在 metadata 區塊外的檔頭 |

## 9. 本機重現

與 CI 相同的指令：

```bash
uv run python scripts/check_conventions.py doc-metadata
uv run python scripts/check_conventions.py doc-dates --base origin/dev
```
