import { type ComponentType, useId } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import { EMPTY_VALUE, formatDateTime } from '@shiro-mlops/shared/i18n/format'
import { type Locale, useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { LineChart as LineChartIcon } from 'lucide-react'
import { useDatasetSeries } from '@/hooks/use-data-explorer'
import { type Messages, useMessages } from '@/i18n/messages'
import type { QueryParams } from '@/lib/api-client'
import { CATEGORY_PALETTES, FORECAST_VINTAGE_COLORS, categoryColor } from '@/lib/chart-palette'
import { brushWindow, type ExplorerWindow } from '@/lib/explorer-window'
import type { Series } from '@/schemas/data-explorer'
import type { ExplorerChartConfig, ExplorerChartType, ExplorerDatasetConfig } from './catalog'
import { type ChartBrush, useChartBrush } from './chart-brush'
import { gapRanges, type PlottedSeries } from './chart-series'
import { explorerFieldLabel } from './field-format'
import { type ChartBodyProps, SeriesLineChart } from './series-line-chart'
import { CHART_DEFAULTS, type ChartSearch, type ChartSearchKey } from './use-explorer-query'

const CHART_RENDERERS: Record<ExplorerChartType, ComponentType<ChartBodyProps>> = {
  line: SeriesLineChart,
}

const BUCKET_OPTIONS = ['auto', 'raw', '1h', '1d'] as const
const AGG_OPTIONS = ['avg', 'min', 'max'] as const
const INVALID_QUERY_STATUS = 422
const DATABASE_UNAVAILABLE_STATUS = 503

type BucketOption = (typeof BUCKET_OPTIONS)[number]

interface ExplorerChartCardProps {
  dataset: ExplorerDatasetConfig
  chart: ExplorerChartConfig
  // The same window and filters the table uses, so chart and table always show one slice.
  query: Record<string, string | undefined>
  chartSearch: ChartSearch
  onSettingChange: (key: ChartSearchKey, value: string) => void
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
  const bucket = optionOr(chartSearch.bucket, BUCKET_OPTIONS, 'auto')
  const agg = optionOr(chartSearch.agg, AGG_OPTIONS, 'avg')
  const prompt = missingFilterPrompt(chart, query, m)
  const seriesQuery = useDatasetSeries(chart.seriesApiPath, seriesParams(chart, query, chartSearch), !prompt)
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
              {chartText.applied(chartText.buckets[seriesQuery.data.bucket], seriesQuery.data.agg ? chartText.aggs[seriesQuery.data.agg] : EMPTY_VALUE)}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <ChartSelect
            label={chartText.bucket}
            value={bucket}
            options={BUCKET_OPTIONS.map((option) => [option, chartText.buckets[option]])}
            onChange={(value) => onSettingChange('bucket', value)}
          />
          <ChartSelect
            label={chartText.agg}
            value={agg}
            disabled={bucket === 'raw'}
            options={AGG_OPTIONS.map((option) => [option, chartText.aggs[option]])}
            onChange={(value) => onSettingChange('agg', value)}
          />
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
  return (
    <>
      <div className="cursor-crosshair select-none">
        <Renderer series={plotted} brush={brush} />
      </div>
      <p className="mt-2 text-xs text-slate-500">{text.brushHint}</p>
      {gapRanges(plotted).length > 0 && (
        <p className="mt-2 flex items-center gap-2 text-xs text-slate-400">
          <span className="inline-block h-3 w-4 rounded-sm bg-slate-500/30" />
          {text.gapLegend}
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
  const id = useId()
  return (
    <span className="flex items-center gap-2">
      <label htmlFor={id} className="text-slate-400">
        {label}
      </label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-lg border border-slate-800 bg-slate-900 px-2 py-1 text-slate-200 disabled:opacity-50"
      >
        {options.map(([option, text]) => (
          <option key={option} value={option}>
            {text}
          </option>
        ))}
      </select>
    </span>
  )
}

function seriesParams(chart: ExplorerChartConfig, query: Record<string, string | undefined>, chartSearch: ChartSearch): QueryParams {
  return {
    ...query,
    fields: chartSearch.fields ?? chart.fields,
    group_by: chartSearch.group_by,
    bucket: withoutDefault('bucket', chartSearch.bucket),
    agg: withoutDefault('agg', chartSearch.agg),
  }
}

function withoutDefault(key: ChartSearchKey, value: string | string[] | undefined): string | undefined {
  return typeof value === 'string' && value !== CHART_DEFAULTS[key] ? value : undefined
}

function optionOr<T extends string>(value: unknown, options: readonly T[], fallback: T): T {
  return options.includes(value as T) ? (value as T) : fallback
}

function missingFilterPrompt(chart: ExplorerChartConfig, query: Record<string, string | undefined>, m: Messages): string | undefined {
  const required = chart.requiredFilter
  if (!required || query[required.when] !== 'true' || query[required.filter]) return undefined
  return m.explorer.chart.requiresFilter(explorerFieldLabel(required.filter, m), explorerFieldLabel(required.when, m))
}

function plotSeries(series: Series[], chart: ExplorerChartConfig, m: Messages, locale: Locale): PlottedSeries[] {
  return groupedSeries(series, chart, m, locale).map((item) => ({ ...item, connectNulls: chart.sparsePoints }))
}

function groupedSeries(series: Series[], chart: ExplorerChartConfig, m: Messages, locale: Locale): PlottedSeries[] {
  const vintageGroup = chart.vintageGroup
  if (vintageGroup && series.some((item) => item.group[vintageGroup])) return plotVintages(series, vintageGroup, m, locale)
  const multipleFields = new Set(series.map((item) => item.field)).size > 1
  const palette = chart.colorBy ? CATEGORY_PALETTES[chart.colorBy.palette] : undefined
  return series.map((item, index) => ({
    key: `s${index}`,
    name: seriesName(item, multipleFields, m),
    color: categoryColor(palette, chart.colorBy ? item.group[chart.colorBy.group] : undefined, index),
    unit: item.unit,
    points: item.points,
  }))
}

// Newest issue first and brightest; vintages past the ramp share its darkest step. Other group
// values are named only where they tell series apart (e.g. two datasets for one issue time).
function plotVintages(series: Series[], vintageGroup: string, m: Messages, locale: Locale): PlottedSeries[] {
  const issues = [...new Set(series.map((item) => item.group[vintageGroup]))].sort().reverse()
  const multipleFields = new Set(series.map((item) => item.field)).size > 1
  const varyingKeys = Object.keys(series[0].group).filter(
    (key) => key !== vintageGroup && new Set(series.map((item) => item.group[key])).size > 1,
  )
  const ordered = [...series].sort((a, b) => issues.indexOf(a.group[vintageGroup]) - issues.indexOf(b.group[vintageGroup]))
  return ordered.map((item, index) => {
    const rank = Math.min(issues.indexOf(item.group[vintageGroup]), FORECAST_VINTAGE_COLORS.length - 1)
    const vintage = [formatDateTime(item.group[vintageGroup], locale), ...varyingKeys.map((key) => item.group[key])].join(' · ')
    return {
      key: `s${index}`,
      name: multipleFields ? `${explorerFieldLabel(item.field, m)} · ${vintage}` : vintage,
      color: FORECAST_VINTAGE_COLORS[rank],
      unit: item.unit,
      points: item.points,
    }
  })
}

function seriesName(item: Series, multipleFields: boolean, m: Messages): string {
  const fieldLabel = explorerFieldLabel(item.field, m)
  const groupName = Object.values(item.group).join(' / ')
  if (!groupName) return fieldLabel
  return multipleFields ? `${fieldLabel} · ${groupName}` : groupName
}

function seriesErrorMessage(error: unknown, text: Messages['explorer']['chart']): string {
  const status = typeof error === 'object' && error !== null && 'status' in error ? error.status : undefined
  if (status === DATABASE_UNAVAILABLE_STATUS) return text.databaseUnavailable
  if (status !== INVALID_QUERY_STATUS) return text.queryFailed
  const suggested = suggestedBucket(error)
  return suggested ? text.tooManyPoints(text.buckets[suggested]) : text.invalidQuery
}

function suggestedBucket(error: unknown): Exclude<BucketOption, 'auto'> | undefined {
  const data = typeof error === 'object' && error !== null && 'data' in error ? error.data : undefined
  const detail = typeof data === 'object' && data !== null && 'detail' in data ? data.detail : undefined
  const suggested = typeof detail === 'object' && detail !== null && 'suggested_bucket' in detail ? detail.suggested_bucket : undefined
  return suggested === 'raw' || suggested === '1h' || suggested === '1d' ? suggested : undefined
}

