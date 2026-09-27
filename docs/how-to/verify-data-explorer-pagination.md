# 驗證 Data Explorer 微秒分頁

- 建立日期：2026-09-27
- 最後更新：2026-09-27

在專案根目錄執行：

```bash
uv sync --all-extras
uv run pytest tests/unit/test_data_explorer_audit_pagination.py -q
scripts/run-data-explorer-timescaledb-acceptance.sh
```

最後一個指令建立獨立的本機 TimescaleDB 容器與 `pagination_acceptance` 資料庫，執行與 SQLite 相同的觀測批次同秒微秒跨頁案例。腳本的 `EXIT` trap 只移除本次建立的容器；若執行中斷，可用 `docker ps -a --filter name=pagination-acceptance-` 查詢殘留容器，再按名稱移除。

未設定 `DATA_EXPLORER_TIMESCALE_URI` 時，真實資料庫測試自動略過，日常離線測試與 CI 無須啟動資料庫。驗收測試只接受指向 `localhost` 或 `127.0.0.1` 的 `pagination_acceptance` 資料庫。

2026-09-27 執行結果：SQLite 案例通過；隔離容器中的 TimescaleDB 案例通過（1 passed）；腳本已移除該次容器。
