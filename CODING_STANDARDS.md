# Coding Standards

- 建立日期：2026-10-25
- 最後更新：2026-11-21

本檔列出本 repo 特有、需由審查者判斷的規則。可機械判定的規則由 CI 執行（ruff、markdownlint、`scripts/check_conventions.py`），不在此重述。

## 文件

- **Diátaxis 歸位**：How-To 只寫操作步驟與預期結果。CI job 的組成與檢查清單以連結指向 `.github/workflows/ci.yml` 或對應腳本，文件內不重述，避免與 CI 漂移。

## 設定與基礎設施

- **設定字面值單一來源**：連接埠、upstream 主機名稱、映像名稱等設定值，在可行範圍內只在一處定義（Makefile 變數、腳本預設值、Compose 檔），其他位置引用它。無法共用時，在重複處註明須同步的來源檔。
- **非直觀設定附 Why 註解**：行為取決於執行期機制的基礎設施設定，須在設定旁說明原因與所防範的失敗情境。例如 Nginx 以 `resolver` 加變數 upstream 延後 DNS 解析，API 容器重建後才不必重啟 Nginx。
- **本機與 CI 共用的檢查放在腳本**：需要在本機重現的 CI 檢查（Docker smoke、慣例檢查）寫在 `scripts/`，由 Makefile target 與 CI 共同呼叫；workflow YAML 只負責準備環境與呼叫腳本，不內嵌多步驟 shell 流程。
- **回歸檢查以負向對照驗證**：新增防回歸檢查時，確認拿掉修正後該檢查會失敗。例如 upstream 重建檢查先啟動替代容器再移除原容器，避免 Docker 重用同一 IP 使檢查恆過。

## 技術債

- **刻意妥協須登記**：變更若明知採取捷徑（暫時繞過、已知限制、延後的清理），合併前須有 `tech-debt` issue，並於 PR 說明連結；ADR 的延後範圍或後果若會持續產生成本，同樣在該項旁連結 issue。登記格式與償還方式見 [docs/agents/tech-debt.md](docs/agents/tech-debt.md)。
- **順手償還**：變更觸及的區域若有觸發條件已成立的 `tech-debt` issue，於同一 PR 償還或說明延後原因。

## 程式碼註解

- **會被工具讀取的 docstring 是介面文字，不是註解**：FastAPI 路由與 Pydantic schema 的 docstring 會成為 OpenAPI 說明，不可依註解規則刪減；Dagster asset 一律以 `description=` 明示說明，不依賴函式 docstring。
- **引用從 repo 根目錄寫起**：Python 註解提到檔案或目錄時，寫成以 tracked 頂層目錄開頭的完整路徑，例如 `src/shiro_mlops/pipelines/issued_forecast.py`、`tests/fixtures/published/`，不寫 `pipelines/issued_forecast.py` 這類套件內相對路徑；提到 ADR 時寫 `ADR-NNNN`。`comment-refs` 檢查會確認這些路徑與 ADR 存在；字串字面值、含 glob 或佔位符（`*`、`<topic>`、`{name}`）的路徑，以及「第 6 節」這類章節編號不在檢查範圍，章節是否仍對得上由審查者判斷。
- **`comment-refs` 失敗時**：檔案改名就把註解改成新路徑；檔案已刪除就連同失效的說明一起改寫或刪除。註解裡看起來像路徑、但其實是名稱的字樣（例如 MLflow experiment 名稱），改為引用持有該值的常數，不要只為了通過檢查而改寫成不像路徑的樣子。
