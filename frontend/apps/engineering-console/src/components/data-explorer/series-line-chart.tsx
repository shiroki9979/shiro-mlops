import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { EMPTY_VALUE, formatDateTime, formatNumber } from '@shiro-mlops/shared/i18n/format'
import { type Locale, useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { CHART_AXIS, CHART_GAP_BAND, CHART_GRID } from '@/lib/chart-palette'
import { type ChartRow, type PlottedSeries, gapRanges, toChartRows } from './chart-series'

// Dots only while they stay legible; denser lines are read from the line and the tooltip.
const MAX_POINTS_WITH_DOTS = 48
const GAP_BAND_OPACITY = 0.18

export interface ChartBodyProps {
  series: PlottedSeries[]
}

// The first unit takes the left axis and a second unit the right one; the spec asks for two
// axes when a chart mixes units.
export function SeriesLineChart({ series }: ChartBodyProps) {
  const locale = useLocale()
  const rows = toChartRows(series)
  const units = [...new Set(series.map((item) => item.unit))].slice(0, 2)
  const showDots = rows.length <= MAX_POINTS_WITH_DOTS
  return (
    <div className="h-[320px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 28, right: 20, left: 10, bottom: 10 }} accessibilityLayer>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} opacity={0.4} vertical={false} />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={['dataMin', 'dataMax']}
            tickFormatter={(instant: number) => formatDateTime(instant, locale)}
            stroke={CHART_AXIS}
            fontSize={11}
            tickLine={false}
            minTickGap={32}
          />
          {units.map((unit, index) => (
            <YAxis
              key={unit}
              yAxisId={unit}
              orientation={index === 0 ? 'left' : 'right'}
              domain={['auto', 'auto']}
              tickFormatter={(value: number) => formatNumber(value, locale)}
              stroke={CHART_AXIS}
              fontSize={11}
              tickLine={false}
              label={{ value: unit, position: 'top', offset: 14, fill: CHART_AXIS, fontSize: 11 }}
            />
          ))}
          {gapRanges(series).map((gap) => (
            <ReferenceArea
              key={gap.from}
              x1={gap.from}
              x2={gap.to}
              yAxisId={units[0]}
              fill={CHART_GAP_BAND}
              fillOpacity={GAP_BAND_OPACITY}
              stroke="none"
              ifOverflow="extendDomain"
            />
          ))}
          <Tooltip content={({ active, payload }) => <SeriesTooltip active={active} row={payload?.[0]?.payload as ChartRow | undefined} series={series} locale={locale} />} />
          <Legend verticalAlign="top" align="right" wrapperStyle={{ paddingBottom: 8, fontSize: '12px' }} />
          {series.map((item) => (
            <Line
              key={item.key}
              type="linear"
              dataKey={item.key}
              name={item.name}
              yAxisId={units.includes(item.unit) ? item.unit : units[0]}
              stroke={item.color}
              strokeWidth={2}
              dot={showDots ? { r: 2, fill: item.color } : false}
              activeDot={{ r: 4 }}
              connectNulls={item.connectNulls ?? false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

interface SeriesTooltipProps {
  active?: boolean
  row?: ChartRow
  series: PlottedSeries[]
  locale: Locale
}

function SeriesTooltip({ active, row, series, locale }: SeriesTooltipProps) {
  if (!active || !row) return null
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/95 p-3 text-xs shadow-xl">
      <p className="mb-1 font-semibold text-slate-200">{formatDateTime(row.t, locale)}</p>
      {series.map((item) => {
        const value = row[item.key]
        return (
          <p key={item.key} className="flex items-center gap-2 text-slate-300">
            <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
            <span>{item.name}</span>
            <span className="ml-auto font-mono">
              {value === null || value === undefined ? EMPTY_VALUE : `${formatNumber(value, locale)} ${item.unit}`}
            </span>
          </p>
        )
      })}
    </div>
  )
}
