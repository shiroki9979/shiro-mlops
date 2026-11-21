import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useDatasetSeries } from '@/hooks/use-data-explorer'
import { useMessages } from '@/i18n/messages'
import type { QueryParams } from '@/lib/api-client'
import { quickRangeWindow } from '@/lib/explorer-window'
import { AuditStatusGrid } from './audit-status-grid'
import type { ExplorerChartConfig, ExplorerDatasetConfig, ExplorerSparklineConfig } from './catalog'
import { explorerFieldLabel } from './field-format'
import { plotSeries } from './plot-series'
import { SeriesSparkline } from './series-sparkline'

// Every card previews 24 hours; the detail limit does not apply to these ranges.
const UNUSED_DETAIL_LIMIT_DAYS = 0
// Hourly status cells need hourly counts whatever `auto` would pick.
const STATUS_GRID_BUCKET = '1h'

interface DatasetSparklineProps {
  dataset: ExplorerDatasetConfig
  // The moment the home page was entered, shared by every card so all previews end together.
  now: Date
}

export function DatasetSparkline({ dataset, now }: DatasetSparklineProps) {
  if (!dataset.chart || !dataset.sparkline) return null
  return <SparklinePreview dataset={dataset} chart={dataset.chart} sparkline={dataset.sparkline} now={now} />
}

interface SparklinePreviewProps extends DatasetSparklineProps {
  chart: ExplorerChartConfig
  sparkline: ExplorerSparklineConfig
}

function SparklinePreview({ dataset, chart, sparkline, now }: SparklinePreviewProps) {
  const m = useMessages()
  const locale = useLocale()
  const range = sparkline.forward ? 'next24Hours' : 'last24Hours'
  const window = quickRangeWindow(range, now, UNUSED_DETAIL_LIMIT_DAYS)
  const isStatusGrid = chart.measure === 'count'
  const params: QueryParams = isStatusGrid
    ? { ...window, bucket: STATUS_GRID_BUCKET }
    : { ...window, fields: sparkline.fields, group_by: sparkline.groupBy }
  const query = useDatasetSeries(chart.seriesApiPath, params)
  const text = m.explorer.sparkline
  const datasetLabel = m.explorer.datasets[dataset.id].label
  const rangeLabel = m.explorer.filters.quickRanges[range]

  if (query.isLoading) return <p className="text-xs text-slate-500">{text.loading}</p>
  if (query.isError || !query.data) return <p className="text-xs text-rose-300">{text.failed}</p>
  if (isStatusGrid) {
    return <AuditStatusGrid series={query.data.series} now={now} label={(summary) => text.statusGridLabel(datasetLabel, rangeLabel, summary)} />
  }
  const plotted = plotSeries(query.data.series, chart, m, locale)
  if (!plotted.some((item) => item.points.some((point) => point.v !== null))) {
    return <p className="text-xs text-slate-500">{text.empty}</p>
  }
  const fieldLabels = (sparkline.fields ?? []).map((field) => explorerFieldLabel(field, m)).join('、')
  const label = text.lineLabel(datasetLabel, rangeLabel, fieldLabels, plotted.map((item) => item.name).join('、'))
  return <SeriesSparkline series={plotted} window={window} label={label} />
}
