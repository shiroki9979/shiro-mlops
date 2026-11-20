# 前端語系與格式

- 建立日期：2026-11-20
- 最後更新：2026-11-20
- 專案版本：`0.4.0`

> 由 `docs/SPEC.md` 第 6 節拆出。

---

> 依 [GitHub #80](https://github.com/shiroki9979/shiro-mlops/issues/80)。程式位於 `frontend/src/i18n/`。

## 1. 語系與字典

- **支援語系**：`zh-TW`（預設）與 `en`。
- **字典型別**：`zh-TW.ts` 為基準字典，`Messages` 型別由其推導；`en.ts` 以 `Messages` 標註，缺鍵或多出的鍵在 `tsc`（`pnpm build`）時失敗。
- **取值方式**：元件經 `useMessages()` 取得目前語系的字典物件（如 `m.nav.dashboard`），插值以函式值表達（如 `m.dashboard.table.title(hours)`）；元件不直接寫 UI 字面值。
- **用詞**：zh-TW 使用 [GLOSSARY.md](../../GLOSSARY.md) 中文正名，en 使用 GLOSSARY 括號內英文；MW、MAPE、CWA、Geocode 等單位與縮寫兩語系皆保留。
- **Data Explorer catalog**：`catalog.ts` 只保存 dataset id、路由、API 路徑、欄位與 filter key；資料集名稱、說明、欄名、filter 標籤與導覽分組標題由字典以 dataset id 與欄位 key 提供。`ExplorerDatasetId` 與 `ExplorerFieldKey` 由字典鍵推導，catalog 引用字典沒有的鍵時 `tsc` 失敗。

## 2. 翻譯邊界

| 類別 | 範圍 |
| :--- | :--- |
| 經字典翻譯 | UI 字串、錯誤與空狀態訊息、Data Explorer 欄名與布林值、API 狀態 enum（`overall`、`availability`、`freshness`、`completeness`、audit `status`） |
| 維持原值 | 區域名、測站編號、機組名稱、`dataset_id` 等資料內容值；篩選 placeholder 中的合法輸入值；後端 `ApiError` 訊息（`detail`）；CSV 表頭與內容；請求參數與 cursor |

`GET /data/status` 回傳的 `label` 不直接顯示；前端以 dataset `id` 查字典，僅在 id 不在 catalog 時回退為 `label`。

## 3. 語系選擇與持久化

- **選擇入口**：僅設定頁提供語系選單，選項以各語言自稱顯示（「正體中文」「English」）。
- **持久化**：獨立 `useLocaleStore`（zustand `persist`，key `shiro-locale`），只保存使用者明確選擇；未選擇時不寫入瀏覽器儲存，不保存自動偵測結果。
- **生效語系**：已保存的選擇優先；否則依序檢查 `navigator.languages`，第一個 `zh*` 對應 `zh-TW`、`en*` 對應 `en`，皆不支援時使用 `zh-TW`。
- **文件語系**：`main.tsx` 在初次 render 前呼叫 `syncDocumentLocale()`，設定 `<html lang>` 與 `document.title`，並於切換語系後同步更新。`index.html` 的靜態值只在 JavaScript 載入前生效。

## 4. 數字與日期時間

- **時區**：所有日期時間格式化經 `src/i18n/format.ts`，明確指定 `timeZone: 'Asia/Taipei'`，不依賴瀏覽器時區；Data Explorer 時間維持整秒格式。
- **數字**：以 `Intl.NumberFormat` 依目前語系分組。
- **Data Explorer 欄位型別**：依欄位 key 的語意對照表辨識時間、日期、量測值、旗標、audit status 與原值；測站編號、Geocode 等識別碼即使形似數字也不格式化。字典沒有的欄位顯示原始 key 與原值。
- **不受語系影響**：請求參數的時間字串（RFC 3339，`+08:00`）、cursor 與 CSV 匯出直接使用 API 原值。

## 5. 不引入 i18n 套件

目前只有兩種語系、字串量約數百，且不需要 ICU 訊息語法、語系檔動態載入或翻譯平台整合；型別化字典搭配原生 `Intl` 即可由 `tsc` 保證鍵完整，不增加相依套件與 bundle 體積。代價是英文單複數等少數規則以函式值手寫。新增語系、需要翻譯平台流程或複數規則顯著增加時，再評估 i18n 套件。

## 6. 測試約定

- vitest 全域 `TZ=UTC`，以已知時間點斷言兩語系皆顯示正確的臺北時間。
- 每個測試前將語系重設為 `zh-TW`（jsdom 預設語言為 `en-US`）；整合測試以字典值斷言，不寫死顯示文字。
