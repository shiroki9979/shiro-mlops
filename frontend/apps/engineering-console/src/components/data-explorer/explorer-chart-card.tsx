import { type ComponentType, useId } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@shiro-mlops/shared/ui/select'
import { EMPTY_VALUE } from '@shiro-mlops/shared/i18n/format'
import { emptyBecause, isNonEmpty, type NonEmptyArray, type QueryView, toQueryView } from '@shiro-mlops/shared/query-view'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { LineChart as LineChartIcon } from 'lucide-react'
import { useDatasetSeries } from '@/hooks/use-data-explorer'
import { type Messages, useMessages } from '@/i18n/messages'
import type { DataExplorerError } from '@/lib/api-client'
import { brushWindow, type ExplorerWindow } from '@/lib/explorer-window'
import {
  AggSchema,
  BucketSchema,
  DEFAULT_AGG,
  type SeriesResponse,
} from '@/schemas/data-explorer'
import type { ExplorerChartConfig, ExplorerChartType, ExplorerDatasetConfig } from './catalog'
import { type ChartBrush, useChartBrush } from './chart-brush'
import { ChartFieldPicker } from './chart-field-picker'
import { bucketBands, type ChartBands, gapRanges, type PlottedSeries } from './chart-series'
import { explorerFieldLabel } from './field-format'
import { plotSeries } from './plot-series'
import { type ChartBodyProps, SeriesLineChart } from './series-line-chart'
import { SeriesStackedAreaChart } from './series-stacked-area-chart'
import { SeriesStatusChart } from './series-status-chart'
import type { ChartSettings, ChartSettingsPatch, SeriesRequest } from './explorer-query-state'

const CHART_RENDERERS: Record<ExplorerChartType, ComponentType<ChartBodyProps>> = {
  line: SeriesLineChart,
  stackedArea: SeriesStackedAreaChart,
  status: SeriesStatusChart,
}

interface ExplorerChartCardProps {
  dataset: ExplorerDatasetConfig
  chart: ExplorerChartConfig
  settings: ChartSettings
  // Built from the same window and filters the table uses, so chart and table show one slice.
  series: SeriesRequest
  onChartChange: (patch: ChartSettingsPatch) => void
  // A brushed range becomes the shared window, the same URL path as the quick ranges and shifts.
  onWindowChange: (window: ExplorerWindow) => void
}

export function ExplorerChartCard({
  dataset,
  chart,
  settings,
  series,
  onChartChange,
  onWindowChange,
}: ExplorerChartCardProps) {
  const m = useMessages()
  const locale = useLocale()
  const chartText = m.explorer.chart
  const prompt = series.kind === 'missingFilter' ? missingFilterPrompt(series, m) : undefined
  const seriesQuery = useDatasetSeries(chart.seriesApiPath, series.kind === 'ready' ? series.params : {}, !prompt)
  const view = toQueryView(seriesQuery, {
    policy: 'data-first',
    settle: (data) => {
      const plottedSeries = plotSeries(data.series, chart, m, locale)
      return isNonEmpty(plottedSeries) ? plottedSeries : emptyBecause('nothingToPlot')
    },
  })
  const plotted = view.kind === 'content' && !prompt ? view.content : []
  const resolvedBucket = seriesQuery.data?.bucket
  const brush = useChartBrush((selection) => {
    if (resolvedBucket) onWindowChange(brushWindow(selection, resolvedBucket, dataset.cadenceSeconds))
  })
  const fieldLabels = (seriesQuery.data?.series.map((item) => item.field) ?? chart.fields)
    .filter((field, index, all) => all.indexOf(field) === index)
    .map((field) => explorerFieldLabel(field, m))
  const figureLabel = chartText.figureLabel(
    m.explorer.datasets[dataset.id].label,
    fieldLabels.join('、'),
    plotted.map((item) => item.name).join('、') || EMPTY_VALUE,
  )

  return (
    <Card role="figure" aria-label={figureLabel}>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 pb-3">
        <div>
          <CardTitle className="text-base flex items-center gap-2">
            <LineChartIcon className="h-4 w-4 text-cyan-400" />
            {chartText.title}
          </CardTitle>
          {seriesQuery.data && (
            <p className="text-xs text-slate-400 mt-1">
              {chartText.applied(chartText.buckets[seriesQuery.data.bucket], appliedAggText(chart, seriesQuery.data.agg, chartText))}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          {chart.groupOptions && settings.groupBy && (
            <ChartSelect
              label={chartText.groupBy}
              value={settings.groupBy}
              options={chart.groupOptions.map((option) => [option, chartText.groupOptions[option]])}
              onChange={(groupBy) => onChartChange({ groupBy })}
            />
          )}
          {chart.fieldOptions && chart.fieldOptions.length > 1 && (
            <ChartFieldPicker
              options={chart.fieldOptions}
              selected={settings.fields}
              onChange={(fields) => onChartChange({ fields })}
            />
          )}
          <ChartSelect
            label={chartText.bucket}
            value={settings.bucket}
            options={BucketSchema.options.map((option) => [option, chartText.buckets[option]])}
            onChange={(bucket) => onChartChange({ bucket })}
          />
          {chart.measure !== 'count' && (
            <ChartSelect
              label={chartText.agg}
              value={settings.agg ?? DEFAULT_AGG}
              disabled={settings.bucket === 'raw'}
              options={AggSchema.options.map((option) => [option, chartText.aggs[option]])}
              onChange={(agg) => onChartChange({ agg })}
            />
          )}
        </div>
      </CardHeader>
      <CardContent>
        {prompt ? (
          <p className="text-sm text-amber-200">{prompt}</p>
        ) : (
          <ChartBody chart={chart} view={view} brush={brush} text={chartText} />
        )}
      </CardContent>
    </Card>
  )
}

interface ChartBodyStateProps {
  chart: ExplorerChartConfig
  view: QueryView<NonEmptyArray<PlottedSeries>, 'nothingToPlot', DataExplorerError>
  brush: ChartBrush
  text: Messages['explorer']['chart']
}

function ChartBody({ chart, view, brush, text }: ChartBodyStateProps) {
  switch (view.kind) {
    case 'loading':
      return <p className="text-sm text-slate-400">{text.loading}</p>
    // Only a missing required filter disables the series, and the card shows its prompt instead.
    case 'disabled':
      return null
    case 'paused':
    case 'error':
      return <p className="text-sm text-rose-300">{seriesErrorMessage(view.error, text)}</p>
    case 'empty':
      return (
        <>
          {view.refreshFailed && <RefreshFailedNotice error={view.error} text={text} />}
          <p className="text-sm text-slate-300">{text.empty}</p>
        </>
      )
    case 'content':
      return (
        <>
          {view.refreshFailed && <RefreshFailedNotice error={view.error} text={text} />}
          <PlottedChart chart={chart} plotted={view.content} brush={brush} text={text} />
        </>
      )
  }
}

function RefreshFailedNotice({ error, text }: { error: DataExplorerError | undefined; text: Messages['explorer']['chart'] }) {
  return <p className="mb-2 text-xs text-rose-300">{text.refreshFailed(seriesErrorMessage(error, text))}</p>
}

interface PlottedChartProps {
  chart: ExplorerChartConfig
  plotted: NonEmptyArray<PlottedSeries>
  brush: ChartBrush
  text: Messages['explorer']['chart']
}

function PlottedChart({ chart, plotted, brush, text }: PlottedChartProps) {
  const Renderer = CHART_RENDERERS[chart.type]
  const bands: ChartBands | undefined = chart.markIncompleteBuckets ? bucketBands(plotted) : undefined
  const gaps = bands?.gaps ?? gapRanges(plotted)
  return (
    <>
      <div className="cursor-crosshair select-none">
        <Renderer series={plotted} brush={brush} bands={bands} />
      </div>
      <p className="mt-2 text-xs text-slate-500">{text.brushHint}</p>
      {gaps.length > 0 && (
        <p className="mt-2 flex items-center gap-2 text-xs text-slate-400">
          <span className="inline-block h-3 w-4 rounded-sm bg-slate-500/30" />
          {text.gapLegend}
        </p>
      )}
      {bands && bands.incomplete.length > 0 && (
        <p className="mt-2 flex items-center gap-2 text-xs text-slate-400">
          <span className="inline-block h-3 w-4 rounded-sm bg-amber-500/30" />
          {text.incompleteLegend}
        </p>
      )}
    </>
  )
}

interface ChartSelectProps<T extends string> {
  label: string
  value: T
  options: [T, string][]
  disabled?: boolean
  onChange: (value: T) => void
}

// Radix reports the chosen value as a string; it is always one of `options`.
function ChartSelect<T extends string>({ label, value, options, disabled, onChange }: ChartSelectProps<T>) {
  const labelId = useId()
  return (
    <span className="flex items-center gap-2">
      <span id={labelId} className="text-slate-400">
        {label}
      </span>
      <Select value={value} disabled={disabled} onValueChange={(next) => onChange(next as T)}>
        <SelectTrigger aria-labelledby={labelId} className="h-auto w-auto gap-2 px-2 py-1 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map(([option, text]) => (
            <SelectItem key={option} value={option}>
              {text}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </span>
  )
}

function appliedAggText(chart: ExplorerChartConfig, agg: SeriesResponse['agg'], text: Messages['explorer']['chart']): string {
  if (chart.measure === 'count') return text.count
  return agg ? text.aggs[agg] : EMPTY_VALUE
}

function missingFilterPrompt(missing: Extract<SeriesRequest, { kind: 'missingFilter' }>, m: Messages): string {
  return m.explorer.chart.requiresFilter(explorerFieldLabel(missing.filter, m), explorerFieldLabel(missing.when, m))
}

// A read paused offline has no error, so it shows the generic failure.
function seriesErrorMessage(error: DataExplorerError | undefined, text: Messages['explorer']['chart']): string {
  if (!error) return text.queryFailed
  switch (error.kind) {
    case 'databaseUnavailable':
      return text.databaseUnavailable
    case 'invalidQuery':
      return error.suggestedBucket ? text.tooManyPoints(text.buckets[error.suggestedBucket]) : text.invalidQuery
    case 'cursorRejected':
    case 'invalidResponse':
    case 'other':
      return text.queryFailed
  }
}

