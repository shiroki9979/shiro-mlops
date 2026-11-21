// zh-TW is the reference dictionary: its shape defines the Messages type that every locale must match.
// Terms follow the Chinese names in GLOSSARY.md; units and abbreviations (MW, MAPE, CWA, Geocode) stay as-is.
export const zhTW = {
  app: {
    brand: 'shiro-mlops',
    tagline: '電力負載動態預測',
    documentTitle: 'shiro-mlops | 台電用電負載動態預測平台',
  },
  common: {
    exportCsv: '匯出 CSV',
    previousPage: '上一頁',
    nextPage: '下一頁',
  },
  nav: {
    sectionTitle: '核心功能',
    dashboard: '即時預測總覽',
    history: '歷史回測與評估',
    liveBadge: '即時',
  },
  header: {
    title: '全台電網負載預測與氣候動態特徵儀表板',
    engine: '動態視界預報引擎',
    toggleTheme: '切換明暗主題',
  },
  localeSwitcher: {
    label: '介面語系',
  },
  dashboard: {
    unavailable: '目前無法取得預報',
    horizon: {
      label: '預測時效：',
      hours: (hours: number) => `${hours} 小時`,
      week: '7 天 (168h)',
    },
    empty: '目前還沒有可顯示的已發布預報',
    noStepsInHorizon: '此預報在所選預測時效內沒有目標小時',
    stale: '預報已超過 24 小時未更新',
    issuedAt: (time: string) => `預報時刻：${time}`,
    predictionSubject: '預測對象：全台',
    autoRefresh: '自動輪詢 (60s)',
    metrics: {
      peakTitle: '尖峰用電預估',
      peakTag: '尖峰',
      peakTime: (time: string) => `預計發生時間：${time}`,
      averageTitle: '區間平均負載',
      averageTag: '平均',
      averageNote: '預測區間負載平穩度指標',
      valleyTitle: '離峰用電低谷',
      valleyTag: '離峰',
      peakValleySpread: (spread: string) => `尖離峰負載差：${spread} MW`,
    },
    chart: {
      loadingTitle: '已發布預報負載走勢圖',
      loading: '載入最新已發布預報中...',
      title: '最新已發布預報負載走勢圖',
      axes: '橫軸：目標小時（台灣時間）｜ 縱軸：預測負載 (MW)',
      loadSeries: '預測負載 (MW)',
    },
    table: {
      loadingTitle: '預測逐時明細表',
      loading: '載入逐時預測明細中...',
      title: (hours: number) => `已發布預報逐時明細表 (共 ${hours} 小時)`,
      targetHour: '目標小時',
      load: '預測負載 (MW)',
      range: (from: number, to: number, total: number) => `顯示第 ${from} 至 ${to} 筆，共 ${total} 筆`,
    },
  },
  history: {
    title: '歷史預測回測與誤差評估',
    description:
      '以過去 72 小時之台電實際用電負載作為基準（Ground Truth），評估 LightGBM 遞迴推論之 MAPE、RMSE 與尖峰誤差。',
    conclusionTitle: '評估結論與建議',
    conclusionAccuracy:
      '1. 在常態日照與氣溫變化下，模型 24h 內 MAPE 控制在 2.14%，符合生產級負載預報要求（< 3.5%）。',
    conclusionPeak: '2. 尖峰用電預警（14:00 - 16:00）命中率達 96.8%，能有效反映高溫氣候引發的空調用電跳升。',
    backtest: {
      title: '72 小時實際用電 vs 模型預測回測對比',
      legend: '藍綠實線：台電實際負載 ｜ 紫色虛線：LightGBM 模型預測值',
      actual: '實際負載：',
      predicted: '預測負載：',
      residual: '殘差誤差：',
      actualSeries: '台電實際負載 (MW)',
      predictedSeries: 'LightGBM 回測預測 (MW)',
    },
    metrics: {
      mape: 'MAPE (平均絕對百分比誤差)',
      mapeBaseline: '優於基準 (<3.5%)',
      mapeNote: '最近 7 天滾動回測評估',
      rmse: 'RMSE (均方根誤差)',
      rmseNote: '整體偏差控制在合理區間',
      mae: 'MAE (平均絕對誤差)',
      maeNote: '平均絕對偏差值',
      peakHitRate: '尖峰預測命中率 (Top 5%)',
      peakHitRateNote: '尖峰時段高準確度預警',
    },
  },
}

export type Messages = typeof zhTW
