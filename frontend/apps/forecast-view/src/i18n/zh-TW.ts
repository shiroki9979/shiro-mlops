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
    history: '預報實績',
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
    stale: (hours: number) => `預報已超過 ${hours} 小時未更新`,
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
    title: '預報實績',
    description: '已發布預報與事後實際負載的對照，最近 30 天。',
    cutoff: (time: string) => `統計截至時刻：${time}`,
    loadError: '目前無法取得預報實績',
    accumulatedDays: (days: number) => `已累積 ${days} 天`,
    staleHint: '預報實績已超過 24 小時未更新',
    metrics: {
      lead24Mape: '提前 24 小時 MAPE',
      lead24Mae: '提前 24 小時 MAE',
    },
    series: {
      title: '最近 30 天提前 24 小時已發布預報與實際負載',
      actual: '實際負載',
      predicted: '預測負載',
      difference: '差值',
      empty: '目前沒有可顯示的對照',
    },
    leadTimeCurve: {
      title: 'MAPE 對提前時數',
      leadTimeAxis: '提前時數（小時）',
      mapeAxis: 'MAPE（%）',
      leadTime: (hours: number) => `提前 ${hours} 小時`,
      mape: 'MAPE',
      mae: 'MAE',
    },
  },
}

export type Messages = typeof zhTW
