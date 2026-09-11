#!/usr/bin/env bash
# Cloud Agent 依賴安裝腳本；必須具備冪等性，可重複執行。
set -euo pipefail

# uv 負責 Python 虛擬環境與依賴管理，預設映像未內建，缺少時才安裝。
if [ ! -x "$HOME/.local/bin/uv" ] && ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

# 依 uv.lock 同步後端依賴（含 dev extras：pytest、ruff、moto）。
uv sync --all-extras

# 依 pnpm-lock.yaml 安裝前端依賴，鎖定版本避免漂移。
pnpm --dir frontend install --frozen-lockfile

# Dagster 要求 DAGSTER_HOME 目錄事先存在，否則 webserver 無法啟動。
mkdir -p .dagster_home
