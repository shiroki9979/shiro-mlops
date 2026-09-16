# 台電全台逐時實際負載來源調查

- 建立日期：2026-09-16
- 對應：#58 Establish canonical hourly actual-load source
- 結論：**沒有驗證到可直接取代既有來源的官方「歷史、全台、逐時實際負載」端點。** 可用的候選是由官方四區即時負載加總而成的未來 10 分鐘觀測序列；它不能回填歷史，且須作為新的衍生契約明確保存。

## 既有資料契約

`raw_taipower_load` 需要每筆具來源時間的全台實際 `load_mw`，可供 `lag_1`、`lag_2`、`lag_24` 與逐時 rolling features 使用；這與即時供需／區域／機組快照在規格中刻意分離。

## 一手來源結果

| 官方來源 | 實測／發布契約 | 結論 |
| --- | --- | --- |
| [過去電力供需資訊（d006005 CSV）](https://service.taipower.com.tw/data/opendata/apply/file/d006005/001.csv)；[官方資料集頁](https://data.gov.tw/dataset/19995) | 官方說明為上一年度至本年度上月的**每日**供需；欄位是 `日期` 與 `尖峰負載(萬瓩)`，資料集頻率每月。2026-09-16 實測為 577 個日列，日期範圍 2025-01-01 至 2026-07-31。 | **拒絕。** 可作每日尖峰分析，不能餵給逐時模型或轉成逐時資料。它是原失效 `d015046` 資料集的現行 service-hosted resource，不是同頻率替代品。 |
| [今日系統供需狀況（d006020 JSON）](https://service.taipower.com.tw/data/opendata/apply/file/d006020/001.json)；[官方資料集頁](https://data.gov.tw/dataset/162595) | 官方聲明每 10 分鐘提供「當日」目前用電；實測有 `records[0].curr_load`（單位萬瓩），但該數值列沒有自己的來源觀測時間。 | **不能直接替代歷史逐時來源。** 若另行核准架構變更，可在擷取時以本系統觀測時間保存、持續累積後降採樣為逐時序列；這是新資料契約，不能將既有快照表直接重標為 canonical load。 |
| [今日區域別用電情況（d006019 CSV）](https://service.taipower.com.tw/data/opendata/apply/file/d006019/001.csv) | 實測為北／中／南／東四列快照，`時間` 格式 `YYYYMMDDTHHMMSS`，另有各區 `用電(萬瓩)`。2026-09-16 23:40 的四區值加總為 2945.7 萬瓩，同時 [d006020](https://service.taipower.com.tw/data/opendata/apply/file/d006020/001.json) `curr_load` 為 2945.6 萬瓩，差 0.1 萬瓩（顯示值四捨五入）。 | **推薦作為未來資料候選。** 僅在四區完整且 `時間` 相同時，將和乘以 10 轉為 MW；保存來源時間與四列 payload，明示為本系統衍生的全台觀測值，不是可重抓的歷史資料。 |
| [各機組發電量即時資訊（d006001 JSON）](https://service.taipower.com.tw/data/opendata/apply/file/d006001/001.json)；[官方資料集頁](https://data.gov.tw/dataset/8931) | 每 10 分鐘的各機組 `淨發電量(MW)` 與 `DateTime`。 | **拒絕。** 發電量不是系統用電負載，且有外購、儲能與系統平衡口徑差異。 |
| [各機組過去發電量（d006010 JSON）](https://service.taipower.com.tw/data/opendata/apply/file/d006010/001.json)；[官方資料集頁](https://data.gov.tw/dataset/37331) | 官方說明為各機組過去每 10 分鐘的淨發電量瞬時值，欄位為 `FUEL_TYPE`、`UNIT_NAME`、`DATETIME`、`NET_P`，並有約三個月發布落後。 | **拒絕。** 有歷史時間序列不代表是負載；不可加總後作為系統實際用電。 |
| [各區域間過去電力潮流量（d006009 JSON）](https://service.taipower.com.tw/data/opendata/apply/file/d006009/001.json)；[官方資料集頁](https://data.gov.tw/dataset/37326) | 官方說明為區域間每 10 分鐘的電力潮流瞬時值；更新時點落後三個月，並註明 EMS 資料可能與正式數值有差異。 | **拒絕。** 潮流量不是全台用電負載；即使有時間序列也不能作為目標值。 |

## 建議與未解風險

1. **不要替換為 d006005。** 先讓 #58 將「無可驗證的同契約端點」記為結果，避免以頻率造假方式恢復 job。
2. 若要恢復未來資料，應建立新的、受規格審核的 canonical series：以 d006019 的來源時間作為 observation time，僅在四區完整且同時時加總為 MW，並定義每小時 slot／聚合規則、保存四列 payload 與缺口；它需要更新資料模型、訓練最小歷史門檻及既有「快照不得作為訓練輸入」邊界。
3. 歷史回補仍未解：官方已驗證的每日資料與區域潮流資料均不符合目標；須向台電取得或發現具有全台負載、來源時間、逐時（或較細）粒度且可公開重抓的正式資料後，才能安全回填。
4. d006020 的 `curr_load` 可作為 d006019 加總的監測對照，但沒有來源時間欄，故不可單獨成為 canonical time series，亦不可補造來源 timestamp。
