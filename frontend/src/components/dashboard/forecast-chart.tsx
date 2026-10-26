import { PredictionItem } from '@/schemas/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDateTime, formatLoadThousands, formatNumber, formatPercent } from '@/i18n/format'
import { type Locale, useLocale } from '@/i18n/locale-store'
import { useMessages } from '@/i18n/use-messages'
import { useDashboardStore } from '@/store/dashboard-store'
import { formatSeriesValue } from './series-format'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

const HUMIDITY_TICK_FRACTION_DIGITS = 0

interface ForecastChartProps {
  predictions?: PredictionItem[]
  isLoading: boolean
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

export function ForecastChart({ predictions, isLoading }: ForecastChartProps) {
  const { showTemperature, showHumidity } = useDashboardStore()
  const locale = useLocale()
  const chartText = useMessages().dashboard.chart

  if (isLoading || !predictions || predictions.length === 0) {
    return (
      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader>
          <CardTitle className="text-base font-semibold text-slate-200">
            {chartText.loadingTitle}
          </CardTitle>
        </CardHeader>
        <CardContent className="h-[420px] flex items-center justify-center">
          <div className="text-center space-y-2">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-cyan-500 border-t-transparent mx-auto" />
            <p className="text-xs text-slate-400">{chartText.loading}</p>
          </div>
        </CardContent>
      </Card>
    )
  }

  // Find min/max for scaling
  const loads = predictions.map((p) => p.predicted_load_mw)
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
              data={predictions}
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
                dataKey="datetime"
                tickFormatter={(val) => formatDateTime(val, locale)}
                stroke="#64748b"
                fontSize={11}
                tickLine={false}
                axisLine={{ stroke: '#334155' }}
                dy={10}
              />
              {/* Left Y Axis: Power Load (MW) */}
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
              {/* Right Y Axis: Temperature (°C) */}
              {showTemperature && (
                <YAxis
                  yAxisId="temp"
                  orientation="right"
                  domain={[15, 40]}
                  tickFormatter={(val) => `${formatNumber(val, locale)}°`}
                  stroke="#f59e0b"
                  fontSize={11}
                  tickLine={false}
                  axisLine={{ stroke: '#334155' }}
                  dx={5}
                />
              )}
              {/* Optional Right Y Axis 2: Humidity (%) */}
              {showHumidity && !showTemperature && (
                <YAxis
                  yAxisId="humidity"
                  orientation="right"
                  domain={[0, 100]}
                  tickFormatter={(val) => formatPercent(val, locale, HUMIDITY_TICK_FRACTION_DIGITS)}
                  stroke="#38bdf8"
                  fontSize={11}
                  tickLine={false}
                  axisLine={{ stroke: '#334155' }}
                  dx={5}
                />
              )}
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
              {/* Temperature Line */}
              {showTemperature && (
                <Line
                  yAxisId="temp"
                  type="monotone"
                  dataKey="temperature"
                  name={chartText.temperatureSeries}
                  stroke="#f59e0b"
                  strokeWidth={2}
                  dot={false}
                  strokeDasharray="4 4"
                />
              )}
              {/* Humidity Line */}
              {showHumidity && (
                <Line
                  yAxisId={showTemperature ? 'temp' : 'humidity'}
                  type="monotone"
                  dataKey="relative_humidity"
                  name={chartText.humiditySeries}
                  stroke="#38bdf8"
                  strokeWidth={1.5}
                  dot={false}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}
