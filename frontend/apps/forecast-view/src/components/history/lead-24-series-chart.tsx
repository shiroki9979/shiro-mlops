import { useId } from 'react'
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

const DIFFERENCE_PERCENT_FRACTION_DIGITS = 2

interface SeriesRow {
  // Absolute instant (epoch ms), so the rows do not depend on the viewer's time zone.
  target_hour: number
  actual_load_mw: number
  predicted_load_mw: number
}

// Only the target hours the export contains are plotted: it omits hours with no pair
// (data-contracts §5.1), and the Forecast View does not disclose them (ADR-0013 §2.2), so the lines
// run straight on from one point to the next and no row stands in for an omitted hour. Sorted by
// absolute instant rather than trusting the order in the JSON.
function toSeriesRows(series: Lead24SeriesPoint[]): SeriesRow[] {
  return series
    .map((point) => ({
      target_hour: Date.parse(point.target_hour),
      actual_load_mw: point.actual_load_mw,
      predicted_load_mw: point.predicted_load_mw,
    }))
    .sort((a, b) => a.target_hour - b.target_hour)
}

// Actual load and the forecast issued 24 hours ahead for each target hour of the last 30 days.
export function Lead24SeriesChart({ series }: { series: Lead24SeriesPoint[] }) {
  const locale = useLocale()
  const seriesText = useMessages().history.series
  const titleId = useId()
  return (
    <Card role="figure" aria-labelledby={titleId} className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
      <CardHeader>
        <CardTitle id={titleId} className="text-base font-semibold text-slate-200">
          {seriesText.title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {series.length === 0 ? (
          // Neutral and without a reason, like the page's other empty states.
          <p className="text-sm text-slate-300">{seriesText.empty}</p>
        ) : (
          <SeriesLines series={series} locale={locale} text={seriesText} />
        )}
      </CardContent>
    </Card>
  )
}

interface SeriesLinesProps {
  series: Lead24SeriesPoint[]
  locale: Locale
  text: Messages['history']['series']
}

function SeriesLines({ series, locale, text: seriesText }: SeriesLinesProps) {
  return (
    <div className="h-[400px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={toSeriesRows(series)}
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
  const loadText = (load: number) => `${formatLoadMW(load, locale)} MW`
  // A percentage of an actual load of 0 has no value, so it shows the empty-value dash.
  const percent = ((predicted - actual) / actual) * 100
  const percentText = Number.isFinite(percent)
    ? formatPercentDelta(percent, locale, DIFFERENCE_PERCENT_FRACTION_DIGITS)
    : EMPTY_VALUE
  const difference = `${formatLoadDelta(predicted - actual, locale)} MW (${percentText})`
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
