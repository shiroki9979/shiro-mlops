import { Bar, BarChart, CartesianGrid, Legend, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatDateTime, formatNumber } from '@shiro-mlops/shared/i18n/format'
import { type Locale, useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'
import { CHART_AXIS, CHART_BRUSH, CHART_GRID, CHART_SURFACE } from '@/lib/chart-palette'
import type { ChartBodyProps } from './series-line-chart'
import type { PlottedSeries } from './chart-series'

const STACK_ID = 'status'
const SEGMENT_GAP_PX = 2
const MAX_BAR_PX = 24
const BRUSH_OPACITY = 0.2

type CountRow = { t: number } & Record<string, number>

// Status counts stacked per bucket. Raw audit points carry one point of value 1 per batch or
// version and may share an instant, so points at one instant add up instead of replacing each other.
export function SeriesStatusChart({ series, brush }: ChartBodyProps) {
  const locale = useLocale()
  const countLabel = useMessages().explorer.chart.count
  const rows = toCountRows(series)
  return (
    <div className="h-[260px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 28, right: 20, left: 10, bottom: 10 }} accessibilityLayer {...brush.handlers}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} opacity={0.4} vertical={false} />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={['dataMin', 'dataMax']}
            padding={{ left: MAX_BAR_PX, right: MAX_BAR_PX }}
            tickFormatter={(instant: number) => formatDateTime(instant, locale)}
            stroke={CHART_AXIS}
            fontSize={11}
            tickLine={false}
            minTickGap={32}
          />
          <YAxis
            allowDecimals={false}
            tickFormatter={(value: number) => formatNumber(value, locale)}
            stroke={CHART_AXIS}
            fontSize={11}
            tickLine={false}
            label={{ value: countLabel, position: 'top', offset: 14, fill: CHART_AXIS, fontSize: 11 }}
          />
          {brush.selection && (
            <ReferenceArea
              x1={brush.selection.from}
              x2={brush.selection.to}
              fill={CHART_BRUSH}
              fillOpacity={BRUSH_OPACITY}
              stroke="none"
            />
          )}
          <Tooltip
            cursor={{ fill: CHART_GRID, fillOpacity: 0.2 }}
            content={({ active, payload }) => (
              <CountTooltip active={active} row={payload?.[0]?.payload as CountRow | undefined} series={series} locale={locale} />
            )}
          />
          <Legend verticalAlign="top" align="right" wrapperStyle={{ paddingBottom: 8, fontSize: '12px' }} />
          {series.map((item) => (
            <Bar
              key={item.key}
              dataKey={item.key}
              name={item.name}
              stackId={STACK_ID}
              fill={item.color}
              stroke={CHART_SURFACE}
              strokeWidth={SEGMENT_GAP_PX}
              maxBarSize={MAX_BAR_PX}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function toCountRows(series: PlottedSeries[]): CountRow[] {
  const rows = new Map<number, CountRow>()
  for (const item of series) {
    for (const point of item.points) {
      const t = Date.parse(point.t)
      const row = rows.get(t) ?? (Object.fromEntries([['t', t], ...series.map((each) => [each.key, 0])]) as CountRow)
      row[item.key] += point.v ?? 0
      rows.set(t, row)
    }
  }
  return [...rows.values()].sort((a, b) => a.t - b.t)
}

interface CountTooltipProps {
  active?: boolean
  row?: CountRow
  series: PlottedSeries[]
  locale: Locale
}

function CountTooltip({ active, row, series, locale }: CountTooltipProps) {
  if (!active || !row) return null
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/95 p-3 text-xs shadow-xl">
      <p className="mb-1 font-semibold text-slate-200">{formatDateTime(row.t, locale)}</p>
      {series.map((item) => (
        <p key={item.key} className="flex items-center gap-2 text-slate-300">
          <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
          <span>{item.name}</span>
          <span className="ml-auto font-mono">{formatNumber(row[item.key], locale)}</span>
        </p>
      ))}
    </div>
  )
}
