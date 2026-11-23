import { type ComponentType, useId } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@shiro-mlops/shared/ui/select'
import { EMPTY_VALUE } from '@shiro-mlops/shared/i18n/format'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { LineChart as LineChartIcon } from 'lucide-react'
import { useDatasetSeries } from '@/hooks/use-data-explorer'
import { type Messages, useMessages } from '@/i18n/messages'
import type { DataExplorerError, QueryParams } from '@/lib/api-client'
import { isFlagOn } from '@/lib/data-explorer'
import { brushWindow, type ExplorerWindow } from '@/lib/explorer-window'
import { AggSchema, BucketSchema, type SeriesResponse } from '@/schemas/data-explorer'
import type { ExplorerChartConfig, ExplorerChartType, ExplorerDatasetConfig } from './catalog'
import { type ChartBrush, useChartBrush } from './chart-brush'
import { ChartFieldPicker } from './chart-field-picker'
import { isDefaultFieldSelection, selectedChartFields } from './chart-fields'
import { bucketBands, type ChartBands, gapRanges, type PlottedSeries } from './chart-series'
import { explorerFieldLabel } from './field-format'
import { plotSeries } from './plot-series'
import { type ChartBodyProps, SeriesLineChart } from './series-line-chart'
import { SeriesStackedAreaChart } from './series-stacked-area-chart'
import { SeriesStatusChart } from './series-status-chart'
import { CHART_DEFAULTS, type ChartSearch, type ChartSearchKey, DEFAULT_AGG, DEFAULT_BUCKET } from './use-explorer-query'

const CHART_RENDERERS: Record<ExplorerChartType, ComponentType<ChartBodyProps>> = {
  line: SeriesLineChart,
  stackedArea: SeriesStackedAreaChart,
  status: SeriesStatusChart,
}

interface ExplorerChartCardProps {
  dataset: ExplorerDatasetConfig
  chart: ExplorerChartConfig
  // The same window and filters the table uses, so chart and table always show one slice.
  query: Record<string, string | undefined>
  chartSearch: ChartSearch
  onSettingChange: (key: ChartSearchKey, value: string | string[] | undefined) => void
  // A brushed range becomes the shared window, the same URL path as the quick ranges and shifts.
  onWindowChange: (window: ExplorerWindow) => void
}

export function ExplorerChartCard({
  dataset,
  chart,
  query,
  chartSearch,
  onSettingChange,
  onWindowChange,
}: ExplorerChartCardProps) {
  const m = useMessages()
  const locale = useLocale()
  const chartText = m.explorer.chart
  const bucket = optionOr(chartSearch.bucket, BucketSchema.options, DEFAULT_BUCKET)
  const agg = optionOr(chartSearch.agg, AggSchema.options, DEFAULT_AGG)
  const fields = selectedChartFields(chartSearch.fields, chart.fields)
  const prompt = missingFilterPrompt(chart, query, m)
  const seriesQuery = useDatasetSeries(chart.seriesApiPath, seriesParams(chart, query, chartSearch, fields), !prompt)
  const plotted = seriesQuery.data && !prompt ? plotSeries(seriesQuery.data.series, chart, m, locale) : []
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
          {chart.groupOptions && (
            <ChartSelect
              label={chartText.groupBy}
              value={optionOr(chartSearch.group_by, chart.groupOptions, chart.groupOptions[0])}
              options={chart.groupOptions.map((option) => [option, chartText.groupOptions[option]])}
              // The API default grouping stays out of the URL, like the default bucket and agg.
              onChange={(value) => onSettingChange('group_by', value === chart.groupOptions?.[0] ? '' : value)}
            />
          )}
          {chart.fieldOptions && chart.fieldOptions.length > 1 && (
            <ChartFieldPicker
              options={chart.fieldOptions}
              selected={fields}
              onChange={(next) => onSettingChange('fields', isDefaultFieldSelection(next, chart.fields) ? undefined : next)}
            />
          )}
          <ChartSelect
            label={chartText.bucket}
            value={bucket}
            options={BucketSchema.options.map((option) => [option, chartText.buckets[option]])}
            onChange={(value) => onSettingChange('bucket', value)}
          />
          {chart.measure !== 'count' && (
            <ChartSelect
              label={chartText.agg}
              value={agg}
              disabled={bucket === 'raw'}
              options={AggSchema.options.map((option) => [option, chartText.aggs[option]])}
              onChange={(value) => onSettingChange('agg', value)}
            />
          )}
        </div>
      </CardHeader>
      <CardContent>
        {prompt ? (
          <p className="text-sm text-amber-200">{prompt}</p>
        ) : (
          <ChartBody chart={chart} query={seriesQuery} plotted={plotted} brush={brush} text={chartText} />
        )}
      </CardContent>
    </Card>
  )
}

interface ChartBodyStateProps {
  chart: ExplorerChartConfig
  query: ReturnType<typeof useDatasetSeries>
  plotted: PlottedSeries[]
  brush: ChartBrush
  text: Messages['explorer']['chart']
}

function ChartBody({ chart, query, plotted, brush, text }: ChartBodyStateProps) {
  if (query.isLoading) return <p className="text-sm text-slate-400">{text.loading}</p>
  if (query.isError) return <p className="text-sm text-rose-300">{seriesErrorMessage(query.error, text)}</p>
  if (plotted.length === 0) return <p className="text-sm text-slate-300">{text.empty}</p>
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

interface ChartSelectProps {
  label: string
  value: string
  options: [string, string][]
  disabled?: boolean
  onChange: (value: string) => void
}

function ChartSelect({ label, value, options, disabled, onChange }: ChartSelectProps) {
  const labelId = useId()
  return (
    <span className="flex items-center gap-2">
      <span id={labelId} className="text-slate-400">
        {label}
      </span>
      <Select value={value} disabled={disabled} onValueChange={onChange}>
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

function seriesParams(
  chart: ExplorerChartConfig,
  query: Record<string, string | undefined>,
  chartSearch: ChartSearch,
  fields: string[],
): QueryParams {
  if (chart.measure === 'count') return { ...seriesFilterValues(chart, query), bucket: withoutDefault('bucket', chartSearch.bucket) }
  return {
    ...seriesFilterValues(chart, query),
    fields,
    group_by: chartSearch.group_by,
    bucket: withoutDefault('bucket', chartSearch.bucket),
    agg: withoutDefault('agg', chartSearch.agg),
  }
}

function appliedAggText(chart: ExplorerChartConfig, agg: SeriesResponse['agg'], text: Messages['explorer']['chart']): string {
  if (chart.measure === 'count') return text.count
  return agg ? text.aggs[agg] : EMPTY_VALUE
}

// The window always travels; dataset filters only when the series endpoint declares them.
function seriesFilterValues(chart: ExplorerChartConfig, query: Record<string, string | undefined>) {
  const allowed = chart.seriesFilters
  if (!allowed) return query
  const { start, end } = query
  return { start, end, ...Object.fromEntries(allowed.map((key) => [key, query[key]])) }
}

function withoutDefault(key: ChartSearchKey, value: string | string[] | undefined): string | undefined {
  return typeof value === 'string' && value !== CHART_DEFAULTS[key] ? value : undefined
}

function optionOr<T extends string>(value: unknown, options: readonly T[], fallback: T): T {
  return options.includes(value as T) ? (value as T) : fallback
}

function missingFilterPrompt(chart: ExplorerChartConfig, query: Record<string, string | undefined>, m: Messages): string | undefined {
  const required = chart.requiredFilter
  if (!required || !isFlagOn(query[required.when]) || query[required.filter]) return undefined
  return m.explorer.chart.requiresFilter(explorerFieldLabel(required.filter, m), explorerFieldLabel(required.when, m))
}

function seriesErrorMessage(error: DataExplorerError, text: Messages['explorer']['chart']): string {
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

