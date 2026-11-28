# 專案發展藍圖 (ROADMAP.md)

> - Created: 2026-08-23
> - Last Updated: 2026-11-28

本文件只是里程碑索引，記錄各里程碑的目標、驗收標準與優先順序。工單內容、完成標準與進度寫在 GitHub issue。現場驗證另開營運驗收 issue，驗收通過才關閉。規則見 [issue-tracker.md](agents/issue-tracker.md)。

本文件不記錄狀態。要知道里程碑做到哪裡，看追蹤 issue 的子項與營運驗收 issue 的開關。

---

## 里程碑

| 里程碑 | 目標 | 驗收標準 | 追蹤 issue | 營運驗收 |
| :--- | :--- | :--- | :--- | :--- |
| **M1: 視覺化儀表板** | React 19 SPA 儀表板，對接 FastAPI 隨需預測 | Vitest 測試與 Vite 生產建置通過 | — | — |
| **M2: 上游中斷韌性與降級預報** | CWA 擷取指數退避重試；serving 依常模降級，拒絕過舊的負載起點 | CWA 擷取中斷時以 `mode: "degraded"` 產出預報；負載起點過舊時回傳 HTTP 503 | [#62](https://github.com/shiroki9979/shiro-mlops/issues/62) | — |
| **M3: 加權天氣與放假日特徵** | 以全台多個氣象代表點的加權天氣與放假日特徵改善動態視界預報 | 能力：多代表點與放假日的離線測試通過。採用：lab 滾動起點回測贏過基線後才修改任務設定 | [#95](https://github.com/shiroki9979/shiro-mlops/issues/95) | [#98](https://github.com/shiroki9979/shiro-mlops/issues/98)（採用研究） |
| **M4: 預報檢視雲端上線** | 以 S3 + CloudFront 公開預先算好的預報檢視；Terraform 與 CD 串接 | release 合併後自動建置並部署預報檢視，雲端顯示地端匯出的最新已發布預報與預報實績 | [#123](https://github.com/shiroki9979/shiro-mlops/issues/123) | [#201](https://github.com/shiroki9979/shiro-mlops/issues/201) |
| **M5: 營運資料檢視器** | 地端唯讀 Data Explorer，檢查電力與氣象入庫資料 | 六個 typed datasets 與 CWA audits 可依領域條件分頁檢視，狀態判讀與自動化測試通過 | [#40](https://github.com/shiroki9979/shiro-mlops/issues/40) | — |
| **M6: 全台逐時實際負載重建** | 由區域供需快照推算逐時負載，恢復訓練與 drift 排程 | 有效逐時觀測達 672 小時後 `dynamic_horizon_forecast` 完成首次訓練，`/ready` 回傳 HTTP 200 | [#59](https://github.com/shiroki9979/shiro-mlops/issues/59)、[#60](https://github.com/shiroki9979/shiro-mlops/issues/60) | [#146](https://github.com/shiroki9979/shiro-mlops/issues/146) |
| **M7: ML 任務解耦** | 以任務設定與任務類型解耦單一負載任務，並以高負載預警、用電型態異常偵測驗證 | 三個 ML 任務皆由任務設定產生資產與排程，並經 `POST /tasks/{task_id}/predict` 提供推論 | [#64](https://github.com/shiroki9979/shiro-mlops/issues/64) | [#147](https://github.com/shiroki9979/shiro-mlops/issues/147)、[#148](https://github.com/shiroki9979/shiro-mlops/issues/148) |
| **M8: 研究空間 (Lab)** | 同庫單向相依的 `lab/` 研究空間：訓練表快照、滾動起點回測與超參數研究 | 快照無損往返、滾動起點回測與研究報告可重現，`uv run --package lab pytest lab/tests` 通過 | [#89](https://github.com/shiroki9979/shiro-mlops/issues/89) | — |
| **M9: 營運資料檢視器視覺化** | Data Explorer 加入圖表、快速時間導覽與緊湊表格，支援趨勢、聚合與分組比較等探索分析 | 八個資料集皆有預設圖，可在圖上框選窗口並在資料集內設定欄位、分組、粒度與聚合；series endpoint 與前端整合測試通過，各工單附本機真實資料截圖 | [#212](https://github.com/shiroki9979/shiro-mlops/issues/212) | — |
| **M11: 研究空間與平台之間的契約** | 研究者以知悉時間唯讀存取凍結資料做研究，需要時交出模型交付包；平台以可服務檢查與評估閘門把關後，由平台維護者釘選為現役模型 | 沿用已註冊的任務類型新增 ML 任務時，0 個 `src/` 變更、0 次映像重建；新增任務類型只需一次通過共用一致性測試的 `src/` PR；既有三個任務類型改用同一種成品格式；標準回測與評估閘門以知悉時間取輸入；一份在 `lab/` 訓練的交付包能走完交付、可服務檢查、評估閘門、釘選與退回，API 不重啟即換模型，每筆產出都帶模型 SHA | [#456](https://github.com/shiroki9979/shiro-mlops/issues/456) | — |

---

## 優先順序與理由

1. **M6、M7 優先於 M3**：M3 的採用要靠回測判定，回測需要足夠的正式資料，資料又要等 M6 累積。M7 在 M6 累積 672 小時的期間進行，完成後再接 M3。
2. **M3 採用需要足夠的評估起點**：M6 只保證累積達門檻後可以訓練。M3 的採用研究另外要求有效評估起點涵蓋至少 7 個日曆日，且贏過基線才修改任務設定（[#98](https://github.com/shiroki9979/shiro-mlops/issues/98)）。
3. **M4 展示依賴 M6 營運驗收**：預報檢視要有內容可看，需先完成首次訓練（[#146](https://github.com/shiroki9979/shiro-mlops/issues/146)）。
4. **M4 內部順序**：與雲端通道無關的地端工作先做，盡早開始累積預報實績，也就是發布已發布預報、預報實績彙整、前端拆分。雲端部署最後做：Terraform state 與 apply 權責由 [#129](https://github.com/shiroki9979/shiro-mlops/issues/129) 定案，CD 由 [#183](https://github.com/shiroki9979/shiro-mlops/issues/183) 實作。工單之間的相依寫在各 issue 開頭的 `Blocked by:`。
5. **M9 與其他里程碑無相依**：M9 只改 Data Explorer 的讀取端點與前端，與 M3、M6、M7 的關鍵路徑無相依，可平行進行，不改變上述順序。
6. **M11 不擋 M3 的採用研究**：M3 的採用照現行「修改任務設定的訓練配方」進行（[#98](https://github.com/shiroki9979/shiro-mlops/issues/98)）；M11 完成後，研究結論才多一條交付成品的路。
7. **M11 內部順序**：先做資料存取（凍結資料與知悉時間，[ADR-0018](adr/0018-access-research-data-through-data-freezes-and-knowledge-time.md)），因為標準回測與評估閘門都靠它取輸入。再做成品格式與任務類型介面（[ADR-0019](adr/0019-serve-models-by-declaration-with-platform-owned-inference.md)），最後才是評估閘門、釘選與生效（[ADR-0020](adr/0020-hand-off-trained-models-and-pin-the-serving-model.md)）。評估閘門需要氣象署預報入庫後至少 14 天的起點。
8. **M11 的主機更新依賴一次 `dev` → `main` 發布**：主機改追 `main` 之前要先發布一次，這次發布也會第一次觸發雲端 CD（M4 的營運驗收 [#201](https://github.com/shiroki9979/shiro-mlops/issues/201)）。可服務檢查與評估閘門的 run 逾時依賴 run monitoring（[#426](https://github.com/shiroki9979/shiro-mlops/issues/426)）。

## 雲端方向

雲端只公開預先算好的預報檢視，地端負責全部運算；雲端沒有 FastAPI，工程主控台只留地端。決策見 [ADR-0013](adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md)、[ADR-0014](adr/0014-keep-engineering-console-local-and-split-frontend-apps.md)、[ADR-0015](adr/0015-publish-forecast-view-as-static-precomputed-output.md)，託管配置見[預報檢視託管規格](reference/forecast-view-hosting.md)。
