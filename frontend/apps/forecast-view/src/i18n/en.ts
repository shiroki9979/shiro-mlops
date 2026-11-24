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
    history: 'Forecast Track Record',
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
  attribution: {
    sourceLabel: 'Data sources: ',
    providers: 'Taiwan Power Company; Central Weather Administration, Ministry of Transportation and Communications',
    statement:
      'The Open Data is made available to the public under the Open Government Data License. Users can make use of it when complying with the conditions and obligations of its terms.',
    licenseLabel: 'License: ',
    licenseLink: 'Open Government Data License, version 1.0',
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
    stale: (hours: number) => `This forecast has not been updated for more than ${hours} hours`,
    issuedAt: (time) => `Forecast time: ${time}`,
    predictionSubject: 'Prediction Subject: Nationwide',
    autoRefresh: (seconds) => `Auto refresh (${seconds}s)`,
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
    title: 'Forecast Track Record',
    description: 'Issued forecasts compared with the actual load that followed, over the last 30 days.',
    cutoff: (time) => `Track record cutoff: ${time}`,
    loadError: 'The forecast track record is unavailable right now',
    accumulatedDays: (days) => `${days} ${days === 1 ? 'day' : 'days'} accumulated so far`,
    staleHint: 'The forecast track record has not been updated for more than 24 hours',
    metrics: {
      lead24Mape: 'MAPE at 24-hour lead time',
      lead24Mae: 'MAE at 24-hour lead time',
    },
    series: {
      title: 'Forecasts issued 24 hours ahead vs actual load, last 30 days',
      actual: 'Actual load',
      predicted: 'Forecast load',
      difference: 'Difference',
      empty: 'Nothing to compare right now',
    },
    leadTimeCurve: {
      title: 'MAPE by lead time',
      leadTimeAxis: 'Lead time (hours)',
      mapeAxis: 'MAPE (%)',
      leadTime: (hours) => `${hours}-hour lead time`,
      mape: 'MAPE',
      mae: 'MAE',
    },
  },
}
