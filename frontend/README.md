# shiro-mlops Frontend Dashboard

- 建立日期：2026-08-23
- 最後更新：2026-09-08

生產級 React 19 + TypeScript + Vite + TanStack 現代化單頁儀表板（SPA），專為台電 1~72 小時動態負載預測與氣候監控所設計。

## 核心技術棧

- **框架與核心**：React 19, TypeScript 5.7, Vite 6
- **路由與狀態**：TanStack Router, TanStack Query v5, Zustand v5
- **資料視覺化**：Recharts (雙軸動態走勢圖), TanStack Table v8
- **樣式與元件**：Tailwind CSS v4, Radix UI Primitives, Lucide Icons, Sonner
- **型別與驗證**：Zod v3, React Hook Form
- **測試框架**：Vitest, React Testing Library, Mock Service Worker (MSW v2), Playwright

## 頁面導航架構

1. **即時預測總覽 (`/`)**：1~72 小時動態用電負載與氣溫雙軸曲線、尖離峰指標卡、逐時明細表與 CSV 匯出。
2. **歷史回測與評估 (`/history`)**：目前以瀏覽器產生的 72 小時示範序列與固定指標呈現回測介面，尚未讀取實際評估結果。
3. **模型漂移監控 (`/monitoring`)**：目前漂移摘要為固定示範資料；快照卡片透過 `/features/latest` 即時讀取台電負載，並非 Feast 或 TimescaleDB 的唯讀檢視。正式營運資料檢視規劃見 [Data Explorer 規格](../docs/SPEC.md#4-營運資料檢視器-data-explorer)。
4. **系統設定與連線診斷 (`/settings`)**：FastAPI 後端連線設定、降級快取模式說明與手動 Payload 推論測試。

## 開發與執行指令

於 `frontend/` 目錄下執行：

```bash
# 安裝依賴
pnpm install

# 啟動 Vite 本地開發伺服器 (預設 http://localhost:5173，/api 代理至 FastAPI http://localhost:8000)
pnpm run dev

# 執行 Vitest 離線單元與整合測試
pnpm run test

# 執行 TypeScript 型別檢查與生產打包
pnpm run build

# 預覽打包產物
pnpm run preview

# 程式碼風格與 Lint 檢查
pnpm run lint
```
