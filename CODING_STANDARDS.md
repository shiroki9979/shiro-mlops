# Coding Standards

- 建立日期：2026-10-25
- 最後更新：2026-10-25

本檔列出本 repo 特有、需由審查者判斷的規則。可機械判定的規則由 CI 執行（ruff、markdownlint、`scripts/check_conventions.py`），不在此重述。

## 文件

- **Diátaxis 歸位**：How-To 只寫操作步驟與預期結果。CI job 的組成與檢查清單以連結指向 `.github/workflows/ci.yml` 或對應腳本，文件內不重述，避免與 CI 漂移。

## 設定與基礎設施

- **設定字面值單一來源**：連接埠、upstream 主機名稱、映像名稱等設定值，在可行範圍內只在一處定義（Makefile 變數、腳本預設值、Compose 檔），其他位置引用它。無法共用時，在重複處註明須同步的來源檔。
- **非直觀設定附 Why 註解**：行為取決於執行期機制的基礎設施設定，須在設定旁說明原因與所防範的失敗情境。例如 Nginx 以 `resolver` 加變數 upstream 延後 DNS 解析，API 容器重建後才不必重啟 Nginx。
- **本機與 CI 共用的檢查放在腳本**：需要在本機重現的 CI 檢查（Docker smoke、慣例檢查）寫在 `scripts/`，由 Makefile target 與 CI 共同呼叫；workflow YAML 只負責準備環境與呼叫腳本，不內嵌多步驟 shell 流程。
- **回歸檢查以負向對照驗證**：新增防回歸檢查時，確認拿掉修正後該檢查會失敗。例如 upstream 重建檢查先啟動替代容器再移除原容器，避免 Docker 重用同一 IP 使檢查恆過。
