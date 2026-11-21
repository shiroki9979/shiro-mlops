# 專案發展藍圖 (ROADMAP.md)

- 建立日期：2026-08-23
- 最後更新：2026-11-21
- 專案版本：`0.4.0`

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

---

## 優先順序與理由

1. **M6、M7 優先於 M3**：M3 的採用要靠回測判定，回測需要足夠的正式資料，資料又要等 M6 累積。M7 在 M6 累積 672 小時的期間進行，完成後再接 M3。
2. **M3 採用需要足夠的評估起點**：M6 只保證累積達門檻後可以訓練。M3 的採用研究另外要求有效評估起點涵蓋至少 7 個日曆日，且贏過基線才修改任務設定（[#98](https://github.com/shiroki9979/shiro-mlops/issues/98)）。
3. **M4 展示依賴 M6 營運驗收**：預報檢視要有內容可看，需先完成首次訓練（[#146](https://github.com/shiroki9979/shiro-mlops/issues/146)）。
4. **M4 內部順序**：與雲端通道無關的地端工作先做，盡早開始累積預報實績，也就是發布已發布預報、預報實績彙整、前端拆分。CD 工單（[#183](https://github.com/shiroki9979/shiro-mlops/issues/183)）依賴前端拆分與 Terraform state 的決定（[#129](https://github.com/shiroki9979/shiro-mlops/issues/129)）。工單之間的相依寫在各 issue 開頭的 `Blocked by:`。

## 雲端方向

雲端只公開預先算好的預報檢視，地端負責全部運算；雲端沒有 FastAPI，工程主控台只留地端。決策見 [ADR-0013](adr/0013-present-forecast-track-record-from-scheduled-issued-forecasts.md)、[ADR-0014](adr/0014-keep-engineering-console-local-and-split-frontend-apps.md)、[ADR-0015](adr/0015-publish-forecast-view-as-static-precomputed-output.md)，託管配置見[預報檢視託管規格](reference/forecast-view-hosting.md)。
