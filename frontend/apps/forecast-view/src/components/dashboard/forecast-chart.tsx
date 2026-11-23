import type { NonEmptyArray } from '@shiro-mlops/shared/query-view'
import type { ForecastStep } from '@/schemas/published'
import { Card, CardContent, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import { formatDateTime, formatLoadThousands } from '@shiro-mlops/shared/i18n/format'
import { type Locale, useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'
import { formatSeriesValue } from './series-format'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

interface ForecastChartProps {
  steps: NonEmptyArray<ForecastStep>
}

interface CustomTooltipProps {
  active?: boolean
  payload?: Array<{
    name: string
    dataKey?: string | number
    value: number
    color: string
  }>
  label?: string
  locale: Locale
}

function CustomTooltip({ active, payload, label, locale }: CustomTooltipProps) {
  if (!active || !payload || !payload.length) {
    return null
  }

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/95 p-3.5 shadow-2xl backdrop-blur-xl text-xs space-y-2">
      <p className="font-semibold text-slate-300 border-b border-slate-800 pb-1 font-mono">
        {label ? formatDateTime(label, locale) : ''}
      </p>
      <div className="space-y-1">
        {payload.map((entry, index) => (
          <div key={index} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-slate-400">
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: entry.color }}
              />
              {entry.name}
            </span>
            <span className="font-mono font-bold text-slate-100">
              {formatSeriesValue(entry.dataKey, entry.value, locale)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function ForecastChart({ steps }: ForecastChartProps) {
  const locale = useLocale()
  const chartText = useMessages().dashboard.chart

  // Find min/max for scaling
  const loads = steps.map((step) => step.predicted_load_mw)
  const minLoad = Math.floor(Math.min(...loads) * 0.95)
  const maxLoad = Math.ceil(Math.max(...loads) * 1.05)

  return (
    <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div>
          <CardTitle className="text-base font-semibold text-slate-200">
            {chartText.title}
          </CardTitle>
          <p className="text-xs text-slate-400 mt-1">
            {chartText.axes}
          </p>
        </div>
      </CardHeader>
      <CardContent>
        <div className="h-[420px] w-full pt-4">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={steps}
              margin={{ top: 10, right: 30, left: 10, bottom: 25 }}
            >
              <defs>
                <linearGradient id="loadGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#06b6d4" stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="#334155"
                opacity={0.4}
                vertical={false}
              />
              <XAxis
                dataKey="target_hour"
                tickFormatter={(val) => formatDateTime(val, locale)}
                stroke="#64748b"
                fontSize={11}
                tickLine={false}
                axisLine={{ stroke: '#334155' }}
                dy={10}
              />
              {/* Y Axis: Predicted Load (MW) */}
              <YAxis
                yAxisId="load"
                domain={[minLoad, maxLoad]}
                tickFormatter={(val) => formatLoadThousands(val, locale)}
                stroke="#06b6d4"
                fontSize={11}
                tickLine={false}
                axisLine={{ stroke: '#334155' }}
                dx={-5}
              />
              <Tooltip content={<CustomTooltip locale={locale} />} />
              <Legend
                verticalAlign="top"
                align="right"
                wrapperStyle={{ paddingBottom: 15, fontSize: '12px' }}
              />
              {/* Power Load Area */}
              <Area
                yAxisId="load"
                type="monotone"
                dataKey="predicted_load_mw"
                name={chartText.loadSeries}
                stroke="#06b6d4"
                strokeWidth={2.5}
                fillOpacity={1}
                fill="url(#loadGradient)"
                activeDot={{ r: 6, fill: '#06b6d4', stroke: '#ffffff', strokeWidth: 2 }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}
