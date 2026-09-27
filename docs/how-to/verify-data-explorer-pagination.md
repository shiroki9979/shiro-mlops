# 驗證 Data Explorer v2 分頁與精確窗口

- 建立日期：2026-09-27
- 最後更新：2026-09-27

在專案根目錄執行離線驗證：

```bash
uv sync --all-extras
uv run pytest tests/ -q
uv run ruff check .
uv run ruff format --check .
cd frontend
pnpm install --frozen-lockfile
pnpm test:integration data-explorer.test.tsx
pnpm build
pnpm lint
```

八個列表使用固定 fixture 檢查閉區間兩端、兩側一微秒、零寬窗口與跨頁結果；四個完整度查詢檢查端點、缺口及窗口外近鄰。SQLite 測試同時涵蓋 aware 與 naive UTC 儲存，區域完整度篩選與預報最新版本解析在兩種格式混存時仍視為同一時間點；SQLite 與 TimescaleDB 共用 `tests/scenarios/` 的情境。前端操作測試檢查帶 cursor 的 400 後「回到第一頁」保留篩選與窗口，以及預報明確／隱含版本的恢復行為；第一頁已有快取時，恢復操作仍須重新取得資料。

在可執行 Docker 的本機環境，另於專案根目錄執行真實資料庫驗收：

```bash
scripts/run-data-explorer-timescaledb-acceptance.sh
```

腳本建立獨立 TimescaleDB 容器與 `pagination_acceptance` 資料庫，設定 `DATA_EXPLORER_TIMESCALE_URI`，執行 `tests/integration/test_data_explorer_timescaledb*.py` 全部案例。所有案例共用連線 fixture，預設使用 UTC，精確窗口案例改以非 UTC 的 `Asia/Taipei` session 執行；fixture 在連線前檢查 URI，僅接受 `localhost` 或 `127.0.0.1` 的 `pagination_acceptance` 資料庫，並統一初始化 schema 與釋放連線。腳本的 `EXIT` trap 僅移除本次建立的容器及其測試資料；若程序異常中止，可用 `docker ps -a --filter name=pagination-acceptance-` 查詢殘留資源。

未設定上述環境變數時，opt-in 測試自動略過，日常 CI 不需資料庫或外部 API。2026-09-27 實跑結果：離線 Python 測試 352 passed、6 skipped；隔離 TimescaleDB 5 passed，容器已清除；Data Explorer 前端操作測試 21 passed。
