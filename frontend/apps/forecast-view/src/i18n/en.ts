import type { Messages } from './zh-TW'

// Terms follow the English names in GLOSSARY.md. The Messages annotation makes tsc reject missing or extra keys.
export const en: Messages = {
  app: {
    brand: 'shiro-mlops',
    tagline: 'Dynamic Load Forecasting',
    documentTitle: 'shiro-mlops | Taipower Dynamic Load Forecasting Platform',
  },
  common: {
    exportCsv: 'Export CSV',
    previousPage: 'Previous',
    nextPage: 'Next',
  },
  nav: {
    sectionTitle: 'Core Features',
    dashboard: 'Live Forecast Overview',
    history: 'Backtesting & Evaluation',
    liveBadge: 'Live',
  },
  header: {
    title: 'Nationwide Grid Load Forecast & Weather Dashboard',
    engine: 'Dynamic Horizon Forecasting Engine',
    toggleTheme: 'Toggle light/dark theme',
  },
  localeSwitcher: {
    label: 'Interface language',
  },
  dashboard: {
    unavailable: 'The forecast is unavailable right now',
    horizon: {
      label: 'Horizon:',
      hours: (hours) => `${hours} hours`,
      week: '7 days (168h)',
    },
    empty: 'There is no issued forecast to show yet',
    noStepsInHorizon: 'This forecast has no target hours within the selected horizon',
    stale: 'This forecast has not been updated for more than 24 hours',
    issuedAt: (time) => `Forecast time: ${time}`,
    predictionSubject: 'Prediction Subject: Nationwide',
    autoRefresh: 'Auto refresh (60s)',
    metrics: {
      peakTitle: 'Forecast Peak Load',
      peakTag: 'Peak',
      peakTime: (time) => `Expected at: ${time}`,
      averageTitle: 'Average Load',
      averageTag: 'AVG',
      averageNote: 'Load stability across the forecast window',
      valleyTitle: 'Off-Peak Valley',
      valleyTag: 'VALLEY',
      peakValleySpread: (spread) => `Peak-to-valley spread: ${spread} MW`,
    },
    chart: {
      loadingTitle: 'Issued Forecast Load Trend',
      loading: 'Loading the latest issued forecast...',
      title: 'Latest Issued Forecast Load Trend',
      axes: 'X axis: target hour (Taiwan time) | Y axis: predicted load (MW)',
      loadSeries: 'Predicted Load (MW)',
    },
    table: {
      loadingTitle: 'Hourly Forecast Details',
      loading: 'Loading hourly forecast details...',
      title: (hours) => `Issued Forecast Hourly Details (${hours} ${hours === 1 ? 'hour' : 'hours'})`,
      targetHour: 'Target Hour',
      load: 'Predicted Load (MW)',
      range: (from, to, total) => `Showing ${from}–${to} of ${total}`,
    },
  },
  history: {
    title: 'Historical Backtesting & Error Evaluation',
    description:
      'Uses the past 72 hours of Taipower actual load as ground truth to evaluate MAPE, RMSE, and peak error of LightGBM recursive inference.',
    conclusionTitle: 'Findings & Recommendations',
    conclusionAccuracy:
      '1. Under typical sunlight and temperature variation, 24h MAPE stays at 2.14%, meeting the production forecasting requirement (< 3.5%).',
    conclusionPeak:
      '2. Peak-load alerts (14:00 - 16:00) reach a 96.8% hit rate, capturing air-conditioning surges driven by hot weather.',
    backtest: {
      title: '72-Hour Actual Load vs Model Forecast Backtest',
      legend: 'Solid teal: Taipower actual load | Dashed purple: LightGBM forecast',
      actual: 'Actual load:',
      predicted: 'Forecast load:',
      residual: 'Residual:',
      actualSeries: 'Taipower Actual Load (MW)',
      predictedSeries: 'LightGBM Backtest Forecast (MW)',
    },
    metrics: {
      mape: 'MAPE (Mean Absolute Percentage Error)',
      mapeBaseline: 'Better than baseline (<3.5%)',
      mapeNote: 'Rolling backtest over the last 7 days',
      rmse: 'RMSE (Root Mean Squared Error)',
      rmseNote: 'Overall error within an acceptable range',
      mae: 'MAE (Mean Absolute Error)',
      maeNote: 'Mean absolute deviation',
      peakHitRate: 'Peak Forecast Hit Rate (Top 5%)',
      peakHitRateNote: 'High-accuracy peak-period alerts',
    },
  },
}
