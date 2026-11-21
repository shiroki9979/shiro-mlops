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
    errorTitle: '無法取得即時推論資料',
    errorFallback: '請檢查後端 API 是否已啟動 (make dev)',
    horizon: {
      label: '預測時效：',
      hours: (hours: number) => `${hours} 小時`,
      week: '7 天 (168h)',
    },
    predictionSubject: '預測對象：全台',
    temperatureToggle: '氣溫曲線 (°C)',
    humidityToggle: '相對濕度 (%)',
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
      maxTemperatureTitle: '最高預估氣溫',
      maxTemperatureTag: 'CWA 氣象',
      celsius: '攝氏度',
      temperatureNote: '溫度敏感度加權分析',
    },
    chart: {
      loadingTitle: '動態預測負載與氣候走勢圖',
      loading: '計算 LightGBM 遞迴負載推論中...',
      title: '動態負載預測與氣候雙軸走勢圖 (1~72h)',
      axes: '左軸：預測用電負載 (MW) ｜ 右軸：CWA 預報氣溫 (°C)',
      loadSeries: '預測負載 (MW)',
      temperatureSeries: '預報氣溫 (°C)',
      humiditySeries: '相對濕度 (%)',
    },
    table: {
      loadingTitle: '預測逐時明細表',
      loading: '載入逐時預測明細中...',
      title: (hours: number) => `逐時推論特徵明細表 (共 ${hours} 小時)`,
      timestamp: '時間戳記',
      load: '預測負載 (MW)',
      temperature: '預報氣溫 (°C)',
      humidity: '相對濕度 (%)',
      status: '狀態',
      inferred: '推論值',
      range: (from: number, to: number, total: number) => `顯示第 ${from} 至 ${to} 筆，共 ${total} 筆`,
    },
  },
  history: {
    title: '預報實績',
    description: '已發布預報與事後實際負載的對照，最近 30 天。',
    cutoff: (time: string) => `統計截至時刻：${time}`,
    loadError: '目前無法取得預報實績',
    metrics: {
      lead24Mape: '提前 24 小時 MAPE',
      lead24Mae: '提前 24 小時 MAE',
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
