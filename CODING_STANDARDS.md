# Coding Standards

> - Created: 2026-10-25
> - Last Updated: 2026-11-24

本檔列出本 repo 特有、需由審查者判斷的規則。可機械判定的規則由 CI 執行（ruff、markdownlint、`scripts/check_conventions.py`），不在此重述。

## 文件

- **Diátaxis 歸位**：How-To 只寫操作步驟與預期結果。CI job 的組成與檢查清單以連結指向 `.github/workflows/ci.yml` 或對應腳本，文件內不重述，避免與 CI 漂移。
- **能改正文就不寫修訂註記**：內容變了就直接改寫受影響的正文，變更經過留在 commit message。只有 ADR 在不能改寫原決策時（例如決策的一部分被後續 ADR 取代，或需要保留原決策的脈絡）才在 `Notes` 寫修訂註記；檔頭格式見 [Markdown 文件 metadata](docs/reference/markdown-metadata.md)。
- **修訂註記的寫法**：一條註記一個清單項目，依日期追加在 `Notes` 末尾，以 `YYYY-MM-DD：` 開頭，寫出受影響的段落（例如 `§2.3`）與改了什麼。不寫票號或 PR 號，追蹤資訊留在 commit 與 PR。

## 設定與基礎設施

- **設定字面值單一來源**：連接埠、upstream 主機名稱、映像名稱等設定值，在可行範圍內只在一處定義（Makefile 變數、腳本預設值、Compose 檔），其他位置引用它。無法共用時，在重複處註明須同步的來源檔。
- **非直觀設定附 Why 註解**：行為取決於執行期機制的基礎設施設定，須在設定旁說明原因與所防範的失敗情境。例如 Nginx 以 `resolver` 加變數 upstream 延後 DNS 解析，API 容器重建後才不必重啟 Nginx。
- **本機與 CI 共用的檢查放在腳本**：需要在本機重現的 CI 檢查（Docker smoke、慣例檢查）寫在 `scripts/`，由 Makefile target 與 CI 共同呼叫；workflow YAML 只負責準備環境與呼叫腳本，不內嵌多步驟 shell 流程。
- **回歸檢查以負向對照驗證**：新增防回歸檢查時，確認拿掉修正後該檢查會失敗。例如 upstream 重建檢查先啟動替代容器再移除原容器，避免 Docker 重用同一 IP 使檢查恆過。

## 前端

- **查詢畫面狀態經共用 module**：讀取遠端資料的元件經 `@shiro-mlops/shared/query-view` 的 `toQueryView` 取得畫面狀態，只宣告資料優先或錯誤優先與空判定；不自行讀 `isLoading`、`isError`、`fetchStatus` 等查詢旗標決定畫面，也不把載入中旗標當 props 傳給子元件。操作控制項不屬畫面狀態，可直接讀旗標，例如 Refresh 按鈕依 `isFetching` 停用與轉圈。hook 若設 `notifyOnChangeProps`，清單須含 `...QUERY_VIEW_FIELDS`，否則畫面狀態漏掉它依賴的變化。

## 技術債

- **刻意妥協須登記**：變更若明知採取捷徑（暫時繞過、已知限制、延後的清理），合併前須有 `tech-debt` issue，並於 PR 說明連結；ADR 的延後範圍或後果若會持續產生成本，同樣在該項旁連結 issue。登記格式與償還方式見 [docs/agents/tech-debt.md](docs/agents/tech-debt.md)。
- **順手償還**：變更觸及的區域若有觸發條件已成立的 `tech-debt` issue，於同一 PR 償還或說明延後原因。

## 程式碼註解

註解種類、`WHY-NOT` 錨點、`SYNC` 路徑與引用路徑等可機械判定的規則，以及檢查失敗時的修法，見 `scripts/check_conventions.py` 的模組 docstring（`uv run python scripts/check_conventions.py --help` 的 `comment-refs` 與 `comment-kinds`）。以下是審查者要判斷的部分。

- **註解不重述程式碼**：註解只記錄程式碼本身說不出的事：為何刻意這樣做、哪些檔案必須一起改、還欠著什麼。換句話說程式碼的註解、分隔線與分節標籤一律刪除，改用命名或函式、模組切分表達；註解寫的理由是否屬實也由審查者確認。
- **何時寫 `WHY-NOT`**：做法看起來像疏失或可以「簡化」、而改掉會造成實際失敗時才寫，理由要說出它防範的失敗；只想指向 ADR 時也用這個形式。名稱選真正受保護的識別字，讓那段程式碼被刪除或改名時檢查跟著失敗。
- **何時寫 `SYNC`**：重複是刻意的、無法改為引用同一來源時才寫（例如 smoke check 重述部署契約，才能檢出漂移），列出每個必須一起修改的檔案。能共用來源就引用，不寫 `SYNC`。
- **引用從 repo 根目錄寫起**：註解提到檔案時寫完整路徑，例如 `src/shiro_mlops/pipelines/issued_forecast.py`，不寫 `pipelines/issued_forecast.py`；`SYNC` 以外的套件內相對路徑不以 tracked 頂層目錄開頭，檢查看不到，由審查者要求改寫。「第 6 節」這類章節編號是否仍對得上也由審查者判斷。
- **標頭不變條件與程式碼同步**：模組或類別 docstring 裡寫下的不變條件（例如「task types 不碰資料層」），描述的程式碼在 PR 中被修改時，同一個 PR 要更新或刪除那條不變條件。
- **會被工具讀取的 docstring 是介面文字，不是註解**：FastAPI 路由與 Pydantic schema 的 docstring 會成為 OpenAPI 說明，不可依註解規則刪減；Dagster asset 一律以 `description=` 明示說明，不依賴函式 docstring。
