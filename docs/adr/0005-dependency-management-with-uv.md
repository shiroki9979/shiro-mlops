# ADR 0005: 採用 uv 作為 Python 套件依賴與虛擬環境管理標準

> - Created: 2026-08-23
> - Last Updated: 2026-08-23
> - Status: Accepted

---

## 脈絡 (Context)

MLOps 專案涉及龐大的依賴關係（Dagster, MLflow, Feast, LightGBM, FastAPI, PyArrow, Pydantic），傳統 `pip` 或 `poetry` 解析與安裝時間長達數分鐘，在 CI/CD 與 Docker 映像檔建置時造成顯著延遲。

---

## 決策 (Decision)

全面採用 **`uv` (Astral)** 進行套件管理、虛擬環境管理與鎖定（`pyproject.toml` + `uv.lock`）：

1. 本地開發與 CI 皆透過 `uv sync` 一鍵建立確定性環境。
2. Dockerfile 中直接使用 `ghcr.io/astral-sh/uv:latest` 加速映像檔依賴安裝。

---

## 取捨分析 (Trade-offs)

### 優點

- **極致速度**：比 Poetry/pip 快 10~100 倍，CI 與 Docker build 時間從數分鐘縮短至數秒。
- **標準 PEP 621 / PEP 517 相容**：直接基於 `pyproject.toml` 宣告，無廠商鎖定。
- **跨平台一致性**：`uv.lock` 確保地端與 CI 環境完全一致。

### 成本與風險

- **新工具成熟度**：團隊需熟悉 `uv` 命令列介面。

### 適用情境

- 依賴龐大且追求極致迭代速度與 CI 效能之現代 Python 專案。
