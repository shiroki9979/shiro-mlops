import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatDateTime, formatNumber } from '@shiro-mlops/shared/i18n/format'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { CHART_AXIS, CHART_BRUSH, CHART_GAP_BAND, CHART_GRID } from '@/lib/chart-palette'
import { type ChartRow, gapRanges, toChartRows } from './chart-series'
import { type ChartBodyProps, SeriesTooltip } from './series-line-chart'

const AREA_FILL_OPACITY = 0.55
const GAP_BAND_OPACITY = 0.18
const BRUSH_OPACITY = 0.2

// `sign` stacks positive values upward and negative values (storage charging) downward from
// zero at every bucket, so a discharging and a charging member never cancel inside one band.
// Each field forms its own stack; a null point breaks its area instead of dropping to zero.
export function SeriesStackedAreaChart({ series, brush }: ChartBodyProps) {
  const locale = useLocale()
  const rows = toChartRows(series)
  const unit = series[0]?.unit
  return (
    <div className="h-[360px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={rows}
          stackOffset="sign"
          margin={{ top: 28, right: 20, left: 10, bottom: 10 }}
          accessibilityLayer
          {...brush.handlers}
        >
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
          <YAxis
            domain={['auto', 'auto']}
            tickFormatter={(value: number) => formatNumber(value, locale)}
            stroke={CHART_AXIS}
            fontSize={11}
            tickLine={false}
            label={{ value: unit, position: 'top', offset: 14, fill: CHART_AXIS, fontSize: 11 }}
          />
          <ReferenceLine y={0} stroke={CHART_AXIS} />
          {gapRanges(series).map((gap) => (
            <ReferenceArea
              key={gap.from}
              x1={gap.from}
              x2={gap.to}
              fill={CHART_GAP_BAND}
              fillOpacity={GAP_BAND_OPACITY}
              stroke="none"
              ifOverflow="extendDomain"
            />
          ))}
          {brush.selection && (
            <ReferenceArea
              x1={brush.selection.from}
              x2={brush.selection.to}
              fill={CHART_BRUSH}
              fillOpacity={BRUSH_OPACITY}
              stroke="none"
            />
          )}
          <Tooltip content={({ active, payload }) => <SeriesTooltip active={active} row={payload?.[0]?.payload as ChartRow | undefined} series={series} locale={locale} />} />
          <Legend verticalAlign="top" align="right" wrapperStyle={{ paddingBottom: 8, fontSize: '12px' }} />
          {series.map((item) => (
            <Area
              key={item.key}
              type="linear"
              dataKey={item.key}
              name={item.name}
              stackId={item.field}
              stroke={item.color}
              fill={item.color}
              fillOpacity={AREA_FILL_OPACITY}
              strokeWidth={1}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
