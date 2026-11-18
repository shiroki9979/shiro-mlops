# ADR-0014：工程主控台只留地端，前端拆成預報檢視與工程主控台兩個應用

> - Created: 2026-11-18
> - Last Updated: 2026-11-18
> - Author: Bo-Xue Huang
> - Status: 已接受
> - Related: [ADR-0001](0001-hybrid-topology-boundary.md)、[ADR-0007](0007-isolate-cwa-access-behind-scheduled-ingestion.md)、[ADR-0011](0011-co-locate-lab-workspace-with-unidirectional-dependency.md)、[ADR-0013](0013-present-forecast-track-record-from-scheduled-issued-forecasts.md)、[GLOSSARY.md](../../GLOSSARY.md)

---

## 1. Context

M4 要把預報檢視公開上雲（[GitHub #123](https://github.com/shiroki9979/shiro-mlops/issues/123)）。前端目前是單一 Vite SPA，同時包含兩個工作區（定義見 GLOSSARY.md）：

- **預報檢視**：`/`、`/history`，可對外公開。
- **工程主控台**：`/monitoring`、`/settings`、`/data/*`（營運資料檢視器八個資料集），僅供可信任工程師使用。

兩者的界線在程式中並不清楚：

- 語系切換放在 `/settings`，匿名觀眾若要切換語系，就得進入工程主控台。
- 每一頁的共用外框都顯示 API 健康徽章（`environment`、`version`、模型載入狀態）與側欄狀態卡，等於在預報檢視揭露系統狀態。
- 營運資料檢視器的導覽只在執行期依 `/health.data_explorer_enabled` 隱藏；程式碼仍送給每位觀眾，直接輸入網址也能進入頁面。

工程主控台若要上雲，雲端必須讀得到營運資料檢視器的全部資料集與監控所需資料。[GitHub #124](https://github.com/shiroki9979/shiro-mlops/issues/124) 的研究指出：通道做法超出每月 10 美元的預算，且會暴露地端；剩下的路是把整個入庫資料同步到雲端，再加上一層驗證。目前可信任工程師只有一人，而且本來就在地端 24/7 運行的工作站旁。

## 2. Decision

### 2.1 工程主控台只留地端

雲端只部署預報檢視。工程主控台只經地端 Docker Compose 的 Nginx 提供，不上雲，也不在雲端加存取控制。

**後端不變條款**：雲端永遠不開放工程主控台的 API。雲端是否有 FastAPI 由 [GitHub #127](https://github.com/shiroki9979/shiro-mlops/issues/127) 決定；但只要有，`ENVIRONMENT=aws` 且設定 `DATA_EXPLORER_ENABLED=true` 時 API 必須啟動失敗，不能只靠預設值關閉。

### 2.2 前端拆成兩個 React 應用

`frontend/` 改為 pnpm workspace：

```text
frontend/
├── apps/
│   ├── forecast-view/          # /、/history
│   └── engineering-console/    # /console/ 之下
└── packages/
    └── shared/
```

- **單向相依**：兩個應用都可依賴 `packages/shared`，但彼此不得 import；`shared` 也不得 import 任何應用。
- **各自的相依清單**：每個應用有自己的 `package.json`；預報檢視不帶工程主控台專用的套件。
- **建置與部署**：雲端只建置並部署 `forecast-view`。地端 Nginx 映像兩個都建置。

### 2.3 `packages/shared` 的收錄標準

只收「兩邊不一致就是 bug」的東西，而不是「兩邊碰巧都用到」的東西：

- **收錄**：
  - shadcn UI 元件、設計 token 與 Tailwind 基底樣式。
  - i18n 機制與語系切換元件。語系偏好的 `localStorage` key 只在這裡定義。
  - [SPEC §6.4](../SPEC.md#64-數字與日期時間) 的數字與日期時間格式函式。
  - `request()` 與 `ApiError`。
- **不收錄，留在各應用**：語系字典、API 端點與 zod schema、外框版面、頁面元件。這些會隨各工作區的需求分道揚鑣；例如 #127 之後，預報檢視可能不再打 `/predict`。

### 2.4 工作區的歸屬

- **語系切換**：屬於觀看者的偏好，不屬於任一工作區。兩個應用的外框各自放置 `shared` 提供的同一個語系切換元件；`/settings` 不再提供語系選單。
- **系統狀態**：API 健康徽章、側欄狀態卡與營運資料檢視器的導覽歸工程主控台；預報檢視的外框不顯示系統狀態。預報檢視要揭露哪些資料時間（例如預報發布時間）由 #127 決定，不以健康徽章代替。
- **`/settings`**：只剩 API 連線資訊與測試推論，完全屬於工程主控台。

### 2.5 地端的網址配置

- 同一個 Nginx、同一個來源：預報檢視在 `/`、`/history`；工程主控台加上 base path，路由變為 `/console/monitoring`、`/console/settings`、`/console/data/*`。
- `/api/` 轉送維持一份，兩個應用共用。同一來源也讓兩個應用共用語系偏好。
- 舊網址（`/monitoring`、`/settings`、`/data/*`）不轉址。

### Rationale & Alternatives Considered

- **選定方案：工程主控台只留地端，前端拆成兩個應用**。「不對外公開」由部署內容保證：雲端的產物根本不含工程主控台。兩個應用之間的依賴方向由套件邊界強制，與 `src/`／`lab/` 的單向相依（[ADR-0011](0011-co-locate-lab-workspace-with-unidirectional-dependency.md)）同一種精神。
- **候選方案 A：工程主控台上雲並加存取控制**（Cognito、CloudFront 簽章 cookie、IP 白名單）。雲端得讀得到營運資料檢視器的全部資料，等於另做一條完整的入庫資料同步管線；來看作品的人無法登入，展示價值接近零。
- **候選方案 B：同一個應用，建置時依變數排除工程主控台路由**。能讓雲端 bundle 不含工程主控台，但兩個工作區仍在同一個專案，邊界只能靠 ESLint 規則守住，日後拆分還得再做一次。
- **候選方案 C：同一個應用，執行期隱藏導覽**。程式碼照樣送給所有觀眾，直接輸入網址仍能進入頁面，「不對外公開」名不副實。
- **候選方案 D：同一個 Vite 專案、兩個入口**。工具設定最少，但「預報檢視不得 import 工程主控台」同樣只能靠 lint 規則。
- **候選方案 E：兩個完全獨立的專案**。最容易搬到不同儲存庫或換技術，也符合 shadcn 把元件複製進專案的慣例。但約 900 行程式碼與 3 支測試要各維護一份，約 15 個設定檔重複；SPEC §6 的格式規則有兩份實作，同來源共用語系偏好變成兩份程式之間的隱性契約；兩份 lockfile 讓 React 與 Tailwind 版本可能漸漸分歧。兩個應用明顯是同一個產品，分歧的成本高於 workspace 一次性的設定成本。
- **候選方案 F：`shared` 連字典的共用段落與外框版面也一起收**。字典與外框會隨各自的工作區演變，放進 `shared` 會讓一邊的改動強迫另一邊重建與重測。
- **候選方案 G：地端用兩個連接埠，或同來源但保留原路徑**。兩個連接埠需要互相設定網址，`/api` 轉送也要寫兩份；保留原路徑則每多一個工程主控台頁面，就要同步修改 Nginx 的路徑分配。
- **候選方案 H：舊網址 301 轉址到 `/console/`**。地端唯一的使用者就是工程師本人，轉址規則只會變成要長期維護的設定，並讓預報檢視所在的根路徑殘留工程主控台的痕跡。

## 3. Consequences

- **正面效益（Positive）**：
  - 雲端部署的前端只有預報檢視；工程主控台的頁面、文案與相依套件都不會到達公網。
  - 預報檢視的外框不再揭露系統狀態，與 GLOSSARY 的定義一致。
  - 雲端不需要入庫資料明細，#127 只需處理預報檢視所需的資料。
  - 語系與格式規則只有一份實作，兩個應用的顯示一致。
- **代價與風險（Trade-offs & Risks）**：
  - 一次性的工具改寫：workspace、TypeScript 專案參照、Tailwind v4 對 `shared` 的掃描、ESLint 與 Vitest 的 per-package 設定、Dockerfile、Nginx、CI 與 smoke check。
  - 工程主控台的網址與測試中的路徑全部改到 `/console/` 之下。
  - `useMessages` 要改成由各應用傳入字典的工廠函式。
  - `shared` 若不守收錄標準，會變成雜物抽屜。
  - 無法從公網使用工程主控台；離開地端時只能看預報檢視。
- **不做／延後範圍（Out of Scope / Deferred）**：
  - 預報檢視在雲端的服務形態、資料通道與可公開欄位：由 #127 決定。
  - 工程主控台的遠端存取（例如 VPN 或 SSH 通道）。
  - 把兩個應用拆到不同儲存庫。

## 4. Compliance

- CI 驗證預報檢視的建置產物不含工程主控台的路徑（`/console`、`/monitoring`、`/data/`）與專用相依。
- ESLint 禁止 `apps/*` 之間互相 import，也禁止 `packages/shared` import 任何應用。
- 地端 Nginx smoke check 涵蓋 `/`、`/history` 與 `/console/`。
- API 測試：`ENVIRONMENT=aws` 且 `DATA_EXPLORER_ENABLED=true` 時啟動失敗。
- Code Review 清單：新增到 `shared` 的程式須符合「不一致就是 bug」的收錄標準；預報檢視不得顯示 `environment`、`version`、模型載入狀態等系統狀態。

## 5. Notes

- 決策經 2026-11-18 的設計訪談定案（[GitHub #126](https://github.com/shiroki9979/shiro-mlops/issues/126)，地圖 [#123](https://github.com/shiroki9979/shiro-mlops/issues/123)）。地圖原把「拆分兩個 React 應用」列為範圍外，本決策將其納入 M4。
- 實作追蹤：[ROADMAP M4](../ROADMAP.md) TICKET-406、TICKET-407。雲端部署工單依賴 TICKET-406。
