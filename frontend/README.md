# shiro-mlops Frontend

- 建立日期：2026-08-23
- 最後更新：2026-11-23

React 19 + TypeScript + Vite + TanStack 的 pnpm workspace，依 [ADR-0014](../docs/adr/0014-keep-engineering-console-local-and-split-frontend-apps.md) 拆成兩個應用與一個共用套件：

```text
frontend/
├── apps/
│   ├── forecast-view/          # 預報檢視：/、/history；雲端只部署這個應用
│   └── engineering-console/    # 工程主控台：base path /console/，只在地端
├── packages/
│   └── shared/                 # UI 元件、設計 token、i18n 機制與語系切換、格式函式、request()、查詢畫面狀態；testing/ 為測試輔助
└── tooling/                    # Vite dev 代理（/api、/published）、workspace 邊界與 bundle 檢查的測試（node --test）
```

兩個應用都可依賴 `packages/shared`，彼此不得 import，`shared` 也不得 import 任何應用；ESLint 強制此規則。`shared` 的收錄標準見 ADR-0014 §2.3，語系與格式規則見 [前端語系與格式](../docs/reference/frontend-locale.md)。

## 核心技術棧

- **框架與核心**：React 19, TypeScript 5.7, Vite 6
- **路由與狀態**：TanStack Router, TanStack Query v5, Zustand v5
- **資料視覺化**：Recharts（預報檢視）
- **樣式與元件**：Tailwind CSS v4, Radix UI Primitives, Lucide Icons, Sonner
- **型別與驗證**：Zod v3
- **測試框架**：Vitest, React Testing Library, Mock Service Worker (MSW v2)

## 頁面導航架構

預報檢視（`apps/forecast-view`）：

1. **即時預測總覽 (`/`)**：最新已發布預報的預測負載、預報時刻、尖離峰指標卡、逐時明細表與 CSV 匯出；讀取 `/published/latest_issued_forecast.json`，`pnpm dev` 時經 Vite proxy 轉送到地端 Compose 的 Nginx（`:8080`）。
2. **預報實績 (`/history`)**：讀取 `/published/forecast_track_record.json`，顯示統計截至時刻、提前 24 小時的 MAPE 與 MAE 指標卡、MAPE 對提前時數曲線與最近 30 天提前 24 小時已發布預報與實際負載的對照；累積未滿 7 天時只顯示累積天數，統計截至時刻超過 24 小時時顯示中性的過舊提示。不呼叫 API；讀取規則見[預報檢視託管 §4](../docs/reference/forecast-view-hosting.md#4-前端讀取-published)。

工程主控台（`apps/engineering-console`，`/console/` 開啟監控頁）：

1. **模型漂移監控 (`/console/monitoring`)**：漂移摘要仍為固定示範資料；資料來源狀態與營運資料檢視器共用 `GET /data/status`，並可 deep-link 至對應資料集。
2. **營運資料檢視器 (`/console/data`)**：本機或 `DATA_EXPLORER_ENABLED` 時可用的唯讀 TimescaleDB 檢視，涵蓋六個 typed datasets 與 CWA audits。契約見 [Data Explorer 規格](../docs/reference/data-explorer.md)。
3. **系統設定與連線診斷 (`/console/settings`)**：FastAPI 後端連線資訊與手動 Payload 推論測試。

兩個應用的外框都有語系切換；API 健康徽章與側欄狀態卡只在工程主控台。

## 開發與執行指令

使用 `package.json` 的 `engines.node` 指定之 Node.js 版本與 `packageManager` 指定之 pnpm 版本。於 `frontend/` 目錄下執行：

```bash
# 啟用 packageManager 指定的 pnpm 並依 lockfile 安裝整個 workspace
corepack enable
pnpm install --frozen-lockfile

# 同時啟動兩個 Vite 開發伺服器（預報檢視的 /published 代理至地端 Nginx http://localhost:8080，工程主控台的 /api 代理至 FastAPI http://localhost:8000）
#   預報檢視 http://localhost:5173、工程主控台 http://localhost:5174/console/
pnpm run dev

# 執行各套件的 Vitest 離線測試與 tooling/ 的 node --test
pnpm run test

# shared 型別檢查，再對兩個應用執行 TypeScript 型別檢查與生產打包
pnpm run build

# 確認預報檢視的建置產物不含工程主控台的路徑與專用相依，也不含隨需推論的 /predict（需先 build；腳本在 scripts/，CI 呼叫同一 Makefile target）
make -C .. frontend-bundle-check

# 程式碼風格、Lint 與 workspace 邊界檢查
pnpm run lint

# 只操作單一套件，例如預覽預報檢視的打包產物
pnpm --filter @shiro-mlops/forecast-view run preview
```

地端 Nginx 映像（[`Dockerfile`](Dockerfile)、[`nginx.conf`](nginx.conf)）同一來源提供兩個應用：預報檢視在根路徑，工程主控台在 `/console/`，`/api/` 轉送共用一份。CI 以相同的 Node.js／pnpm 宣告執行上述 lint、測試、建置與 bundle 檢查，設定見 [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)。
