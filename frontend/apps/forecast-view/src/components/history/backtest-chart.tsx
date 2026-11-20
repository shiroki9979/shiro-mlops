import { Card, CardContent, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import {
  formatDateTime,
  formatLoadDelta,
  formatLoadMW,
  formatLoadThousands,
  formatPercentDelta,
} from '@shiro-mlops/shared/i18n/format'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'
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

const RESIDUAL_PERCENT_FRACTION_DIGITS = 2

// Generate sample 72h historical vs predicted backtest series
function generateBacktestData() {
  const data = []
  const baseTime = new Date()
  baseTime.setHours(baseTime.getHours() - 72, 0, 0, 0)

  for (let i = 0; i < 72; i++) {
    const dt = new Date(baseTime.getTime() + i * 3600000)
    const hour = dt.getHours()
    // Simulated diurnal cycle
    const cycle = Math.sin(((hour - 6) / 24) * 2 * Math.PI)
    const actual = 28000 + cycle * 7000 + (Math.sin(i * 0.5) * 600)
    const errorNoise = (Math.sin(i * 0.8 + 1) * 450) + (Math.cos(i * 0.3) * 200)
    const predicted = actual + errorNoise

    data.push({
      datetime: dt.toISOString(),
      actual_load_mw: actual,
      predicted_load_mw: predicted,
      residual: Math.abs(predicted - actual),
    })
  }
  return data
}

const backtestData = generateBacktestData()

export function BacktestChart() {
  const locale = useLocale()
  const backtestText = useMessages().history.backtest
  return (
    <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
      <CardHeader>
        <CardTitle className="text-base font-semibold text-slate-200">
          {backtestText.title}
        </CardTitle>
        <p className="text-xs text-slate-400">
          {backtestText.legend}
        </p>
      </CardHeader>
      <CardContent>
        <div className="h-[400px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={backtestData}
              margin={{ top: 10, right: 20, left: 10, bottom: 20 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} vertical={false} />
              <XAxis
                dataKey="datetime"
                tickFormatter={(val) => formatDateTime(val, locale)}
                stroke="#64748b"
                fontSize={11}
                tickLine={false}
                dy={10}
              />
              <YAxis
                domain={['auto', 'auto']}
                tickFormatter={(val) => formatLoadThousands(val, locale)}
                stroke="#64748b"
                fontSize={11}
                tickLine={false}
                dx={-5}
              />
              <Tooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null
                  const actual = payload.find((p) => p.dataKey === 'actual_load_mw')?.value as number
                  const pred = payload.find((p) => p.dataKey === 'predicted_load_mw')?.value as number
                  const diff = pred - actual
                  const diffPct = (diff / actual) * 100

                  return (
                    <div className="rounded-xl border border-slate-700 bg-slate-900/95 p-3 shadow-2xl backdrop-blur-xl text-xs space-y-2">
                      <p className="font-semibold text-slate-300 font-mono">
                        {label ? formatDateTime(label as string, locale) : ''}
                      </p>
                      <div className="space-y-1">
                        <div className="flex justify-between gap-4 text-emerald-400">
                          <span>{backtestText.actual}</span>
                          <span className="font-mono font-bold">{formatLoadMW(actual, locale)} MW</span>
                        </div>
                        <div className="flex justify-between gap-4 text-cyan-300">
                          <span>{backtestText.predicted}</span>
                          <span className="font-mono font-bold">{formatLoadMW(pred, locale)} MW</span>
                        </div>
                        <div className="flex justify-between gap-4 text-slate-400 border-t border-slate-800 pt-1">
                          <span>{backtestText.residual}</span>
                          <span className="font-mono font-semibold text-amber-300">
                            {formatLoadDelta(diff, locale)} MW ({formatPercentDelta(diffPct, locale, RESIDUAL_PERCENT_FRACTION_DIGITS)})
                          </span>
                        </div>
                      </div>
                    </div>
                  )
                }}
              />
              <Legend
                verticalAlign="top"
                align="right"
                wrapperStyle={{ paddingBottom: 15, fontSize: '12px' }}
              />
              <Line
                type="monotone"
                dataKey="actual_load_mw"
                name={backtestText.actualSeries}
                stroke="#10b981"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="predicted_load_mw"
                name={backtestText.predictedSeries}
                stroke="#06b6d4"
                strokeWidth={2}
                strokeDasharray="4 4"
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}
