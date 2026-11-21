import { Card, CardContent, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import {
  EMPTY_VALUE,
  formatDateTime,
  formatLoadDelta,
  formatLoadMW,
  formatLoadThousands,
  formatPercentDelta,
} from '@shiro-mlops/shared/i18n/format'
import { type Locale, useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { type Messages, useMessages } from '@/i18n/messages'
import type { ForecastTrackRecord } from '@/schemas/published'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

type Lead24SeriesPoint = NonNullable<ForecastTrackRecord['metrics']>['lead_24_series'][number]

const HOUR_MS = 60 * 60 * 1000
const DIFFERENCE_PERCENT_FRACTION_DIGITS = 2

interface SeriesRow {
  // Absolute instant (epoch ms), so the grid does not depend on the viewer's time zone.
  target_hour: number
  actual_load_mw: number | null
  predicted_load_mw: number | null
}

// The export omits target hours with no pair (data-contracts §5.1). Laying the points on an hourly
// grid from the first to the last gives each missing hour a row of nulls, so the lines break there
// instead of being drawn across it; no value is made up.
function toHourlyGrid(series: Lead24SeriesPoint[]): SeriesRow[] {
  if (series.length === 0) return []
  const byInstant = new Map(series.map((point) => [Date.parse(point.target_hour), point]))
  const first = Date.parse(series[0].target_hour)
  const last = Date.parse(series[series.length - 1].target_hour)
  const rows: SeriesRow[] = []
  for (let instant = first; instant <= last; instant += HOUR_MS) {
    const point = byInstant.get(instant)
    rows.push({
      target_hour: instant,
      actual_load_mw: point?.actual_load_mw ?? null,
      predicted_load_mw: point?.predicted_load_mw ?? null,
    })
  }
  return rows
}

// Actual load and the forecast issued 24 hours ahead for each target hour of the last 30 days.
export function Lead24SeriesChart({ series }: { series: Lead24SeriesPoint[] }) {
  const locale = useLocale()
  const seriesText = useMessages().history.series
  return (
    <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
      <CardHeader>
        <CardTitle className="text-base font-semibold text-slate-200">{seriesText.title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[400px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={toHourlyGrid(series)}
              margin={{ top: 10, right: 20, left: 10, bottom: 20 }}
              accessibilityLayer
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} vertical={false} />
              <XAxis
                dataKey="target_hour"
                tickFormatter={(instant: number) => formatDateTime(instant, locale)}
                stroke="#64748b"
                fontSize={11}
                tickLine={false}
                minTickGap={24}
                dy={10}
              />
              <YAxis
                domain={['auto', 'auto']}
                tickFormatter={(load: number) => formatLoadThousands(load, locale)}
                stroke="#64748b"
                fontSize={11}
                tickLine={false}
                dx={-5}
              />
              <Tooltip
                filterNull={false}
                content={({ active, payload }) => (
                  <SeriesTooltip
                    row={active ? (payload?.[0]?.payload as SeriesRow | undefined) : undefined}
                    locale={locale}
                    text={seriesText}
                  />
                )}
              />
              <Legend verticalAlign="top" align="right" wrapperStyle={{ paddingBottom: 15, fontSize: '12px' }} />
              <Line
                type="monotone"
                dataKey="actual_load_mw"
                name={seriesText.actual}
                stroke="#10b981"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="predicted_load_mw"
                name={seriesText.predicted}
                stroke="#06b6d4"
                strokeWidth={2}
                strokeDasharray="4 4"
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}

interface SeriesTooltipProps {
  row: SeriesRow | undefined
  locale: Locale
  text: Messages['history']['series']
}

function SeriesTooltip({ row, locale, text }: SeriesTooltipProps) {
  if (!row) return null
  const { actual_load_mw: actual, predicted_load_mw: predicted } = row
  const loadText = (load: number | null) => (load === null ? EMPTY_VALUE : `${formatLoadMW(load, locale)} MW`)
  const difference =
    actual === null || predicted === null
      ? EMPTY_VALUE
      : `${formatLoadDelta(predicted - actual, locale)} MW (${formatPercentDelta(
          ((predicted - actual) / actual) * 100,
          locale,
          DIFFERENCE_PERCENT_FRACTION_DIGITS,
        )})`
  return (
    <div
      role="tooltip"
      className="rounded-xl border border-slate-700 bg-slate-900/95 p-3 shadow-2xl backdrop-blur-xl text-xs space-y-2"
    >
      <p className="font-semibold text-slate-300 font-mono">{formatDateTime(row.target_hour, locale)}</p>
      <dl className="space-y-1">
        <TooltipRow label={text.actual} value={loadText(actual)} className="text-emerald-400" />
        <TooltipRow label={text.predicted} value={loadText(predicted)} className="text-cyan-300" />
        <TooltipRow
          label={text.difference}
          value={difference}
          className="text-slate-400 border-t border-slate-800 pt-1"
        />
      </dl>
    </div>
  )
}

function TooltipRow({ label, value, className }: { label: string; value: string; className: string }) {
  return (
    <div className={`flex justify-between gap-4 ${className}`}>
      <dt>{label}</dt>
      <dd className="font-mono font-bold">{value}</dd>
    </div>
  )
}
