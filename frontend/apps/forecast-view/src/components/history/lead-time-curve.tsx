import { useId } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import { EMPTY_VALUE, formatLoadMW, formatPercent } from '@shiro-mlops/shared/i18n/format'
import { type Locale, useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { type Messages, useMessages } from '@/i18n/messages'
import type { LeadTimeMetrics } from '@/schemas/published'

const MAPE_FRACTION_DIGITS = 2
const MAPE_TICK_FRACTION_DIGITS = 0
// Lead times 1–168 h (data-contracts §5.1); ticks at the start and every whole day.
const LEAD_TIME_DOMAIN: [number, number] = [1, 168]
const LEAD_TIME_TICKS = [1, 24, 48, 72, 96, 120, 144, 168]

// MAPE against lead time 1–168 h, with MAE in the tooltip. A cell with no pairs (mape null) is a
// gap in the line, never 0; lead time 168 is always null in normal operation, so the line ends in one.
export function LeadTimeCurve({ curve }: { curve: LeadTimeMetrics[] }) {
  const locale = useLocale()
  const text = useMessages().history.leadTimeCurve
  const titleId = useId()
  return (
    <Card role="figure" aria-labelledby={titleId} className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
      <CardHeader>
        <CardTitle id={titleId} className="text-base font-semibold text-slate-200">
          {text.title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[320px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={curve} margin={{ top: 10, right: 20, left: 10, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} vertical={false} />
              <XAxis
                dataKey="lead_time_hours"
                type="number"
                domain={LEAD_TIME_DOMAIN}
                ticks={LEAD_TIME_TICKS}
                interval={0}
                stroke="#64748b"
                fontSize={11}
                tickLine={false}
                dy={10}
                label={{ value: text.leadTimeAxis, position: 'insideBottom', offset: -15, fill: '#94a3b8', fontSize: 11 }}
              />
              <YAxis
                domain={[0, 'auto']}
                tickFormatter={(value: number) => formatPercent(value, locale, MAPE_TICK_FRACTION_DIGITS)}
                stroke="#64748b"
                fontSize={11}
                tickLine={false}
                dx={-5}
                label={{ value: text.mapeAxis, angle: -90, position: 'insideLeft', fill: '#94a3b8', fontSize: 11 }}
              />
              <Tooltip
                filterNull={false}
                content={({ active, payload }) => (
                  <LeadTimeTooltip
                    cell={active ? (payload?.[0]?.payload as LeadTimeMetrics | undefined) : undefined}
                    locale={locale}
                    text={text}
                  />
                )}
              />
              <Line
                type="monotone"
                dataKey="mape"
                name={text.mape}
                stroke="#10b981"
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}

interface LeadTimeTooltipProps {
  cell: LeadTimeMetrics | undefined
  locale: Locale
  text: Messages['history']['leadTimeCurve']
}

function LeadTimeTooltip({ cell, locale, text }: LeadTimeTooltipProps) {
  if (!cell) return null
  const mape = cell.mape === null ? EMPTY_VALUE : formatPercent(cell.mape, locale, MAPE_FRACTION_DIGITS)
  const mae = cell.mae === null ? EMPTY_VALUE : `${formatLoadMW(cell.mae, locale)} MW`
  return (
    <div
      role="tooltip"
      className="rounded-xl border border-slate-700 bg-slate-900/95 p-3 shadow-2xl backdrop-blur-xl text-xs space-y-2"
    >
      <p className="font-semibold text-slate-300 font-mono">{text.leadTime(cell.lead_time_hours)}</p>
      <div className="space-y-1">
        <div className="flex justify-between gap-4 text-emerald-400">
          <span>{text.mape}</span>
          <span className="font-mono font-bold">{mape}</span>
        </div>
        <div className="flex justify-between gap-4 text-indigo-300">
          <span>{text.mae}</span>
          <span className="font-mono font-bold">{mae}</span>
        </div>
      </div>
    </div>
  )
}
