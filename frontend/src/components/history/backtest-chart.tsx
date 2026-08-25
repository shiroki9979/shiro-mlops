import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDateTime, formatLoadMW } from '@/lib/utils'
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
  return (
    <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
      <CardHeader>
        <CardTitle className="text-base font-semibold text-slate-200">
          72 小時實際用電 vs 模型預測回測對比 (Backtesting Curve)
        </CardTitle>
        <p className="text-xs text-slate-400">
          藍綠實線：台電實際負載 ｜ 紫色虛線：LightGBM 模型預測值
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
                tickFormatter={(val) => formatDateTime(val)}
                stroke="#64748b"
                fontSize={11}
                tickLine={false}
                dy={10}
              />
              <YAxis
                domain={['auto', 'auto']}
                tickFormatter={(val) => `${(val / 1000).toFixed(1)}k`}
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
                        {label ? formatDateTime(label as string) : ''}
                      </p>
                      <div className="space-y-1">
                        <div className="flex justify-between gap-4 text-emerald-400">
                          <span>實際負載：</span>
                          <span className="font-mono font-bold">{formatLoadMW(actual)} MW</span>
                        </div>
                        <div className="flex justify-between gap-4 text-cyan-300">
                          <span>預測負載：</span>
                          <span className="font-mono font-bold">{formatLoadMW(pred)} MW</span>
                        </div>
                        <div className="flex justify-between gap-4 text-slate-400 border-t border-slate-800 pt-1">
                          <span>殘差誤差：</span>
                          <span className="font-mono font-semibold text-amber-300">
                            {diff >= 0 ? `+${formatLoadMW(diff)}` : formatLoadMW(diff)} MW ({diffPct.toFixed(2)}%)
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
                name="台電實際負載 (MW)"
                stroke="#10b981"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="predicted_load_mw"
                name="LightGBM 回測預測 (MW)"
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
