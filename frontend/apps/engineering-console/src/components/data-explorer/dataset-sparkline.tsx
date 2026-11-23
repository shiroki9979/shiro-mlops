import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { emptyBecause, toQueryView } from '@shiro-mlops/shared/query-view'
import { useDatasetSeries } from '@/hooks/use-data-explorer'
import { useMessages } from '@/i18n/messages'
import type { QueryParams } from '@/lib/api-client'
import { quickRangeWindow } from '@/lib/explorer-window'
import type { ResolvedBucket } from '@/schemas/data-explorer'
import { AuditStatusGrid } from './audit-status-grid'
import type { ExplorerChartConfig, ExplorerDatasetConfig, ExplorerSparklineConfig } from './catalog'
import { explorerFieldLabel } from './field-format'
import { plotSeries } from './plot-series'
import { SeriesSparkline } from './series-sparkline'

// Every card previews 24 hours; the detail limit does not apply to these ranges.
const UNUSED_DETAIL_LIMIT_DAYS = 0
// Hourly status cells need hourly counts whatever `auto` would pick.
const STATUS_GRID_BUCKET: ResolvedBucket = '1h'

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
  const view = toQueryView(useDatasetSeries(chart.seriesApiPath, params), {
    policy: 'data-first',
    // The status grid draws hours without records too, so only the line preview can be empty.
    settle: (data) => {
      if (isStatusGrid) return { preview: 'grid' as const, series: data.series }
      const plotted = plotSeries(data.series, chart, m, locale)
      return plotted.some((item) => item.points.some((point) => point.v !== null))
        ? { preview: 'line' as const, series: plotted }
        : emptyBecause('noValues')
    },
  })
  const text = m.explorer.sparkline
  const datasetLabel = m.explorer.datasets[dataset.id].label
  const rangeLabel = m.explorer.filters.quickRanges[range]

  switch (view.kind) {
    case 'loading':
      return <p className="text-xs text-slate-500">{text.loading}</p>
    // The series query is never disabled; it falls in with the failures only so every kind is handled.
    case 'disabled':
    case 'paused':
    case 'error':
      return <p className="text-xs text-rose-300">{text.failed}</p>
    case 'empty':
      return (
        <>
          <p className="text-xs text-slate-500">{text.empty}</p>
          {view.refreshFailed && <p className="text-xs text-amber-300">{text.refreshFailed}</p>}
        </>
      )
    case 'content': {
      const { content } = view
      const preview =
        content.preview === 'grid' ? (
          <AuditStatusGrid
            series={content.series}
            now={now}
            label={(summary) => text.statusGridLabel(datasetLabel, rangeLabel, summary)}
          />
        ) : (
          <SeriesSparkline
            series={content.series}
            window={window}
            label={text.lineLabel(
              datasetLabel,
              rangeLabel,
              (sparkline.fields ?? []).map((field) => explorerFieldLabel(field, m)).join('、'),
              content.series.map((item) => item.name).join('、'),
            )}
          />
        )
      return (
        <>
          {preview}
          {view.refreshFailed && <p className="text-xs text-amber-300">{text.refreshFailed}</p>}
        </>
      )
    }
  }
}
