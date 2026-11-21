import { PredictionItem } from '@/schemas/api'
import { Card, CardContent } from '@shiro-mlops/shared/ui/card'
import { EMPTY_VALUE, formatDateTime, formatLoadMW, formatTemperature } from '@shiro-mlops/shared/i18n/format'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'
import { Activity, ArrowUpRight, Gauge, ThermometerSun, Zap } from 'lucide-react'

interface MetricCardsProps {
  predictions?: PredictionItem[]
  isLoading: boolean
}

export function MetricCards({ predictions, isLoading }: MetricCardsProps) {
  const m = useMessages()
  const locale = useLocale()
  const metricsText = m.dashboard.metrics

  if (isLoading || !predictions || predictions.length === 0) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <Card key={i} className="animate-pulse bg-slate-900/50 border-slate-800">
            <CardContent className="p-5 space-y-3">
              <div className="h-4 w-24 bg-slate-800 rounded" />
              <div className="h-8 w-32 bg-slate-800 rounded" />
              <div className="h-3 w-40 bg-slate-800 rounded" />
            </CardContent>
          </Card>
        ))}
      </div>
    )
  }

  // Calculate metrics
  const loads = predictions.map((p) => p.predicted_load_mw)
  const temperatures = predictions.map((p) => p.temperature)

  const peakLoad = Math.max(...loads)
  const avgLoad = loads.reduce((a, b) => a + b, 0) / loads.length
  const minLoad = Math.min(...loads)
  const maxTemp = Math.max(...temperatures)

  const peakItem = predictions.find((p) => p.predicted_load_mw === peakLoad)

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* Peak Load Card */}
      <Card className="border-cyan-500/20 bg-gradient-to-br from-slate-900 via-slate-900 to-cyan-950/30">
        <CardContent className="p-5 space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5 font-medium">
              <Zap className="h-4 w-4 text-cyan-400" />
              {metricsText.peakTitle}
            </span>
            <span className="flex items-center text-cyan-400 text-[11px]">
              {metricsText.peakTag} <ArrowUpRight className="h-3 w-3" />
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-100 font-mono tracking-tight">
              {formatLoadMW(peakLoad, locale)}
            </span>
            <span className="text-xs text-slate-400">MW</span>
          </div>
          <p className="text-[11px] text-slate-500 truncate">
            {metricsText.peakTime(peakItem ? formatDateTime(peakItem.datetime, locale) : EMPTY_VALUE)}
          </p>
        </CardContent>
      </Card>

      {/* Average Load Card */}
      <Card className="border-slate-800 bg-slate-900/70">
        <CardContent className="p-5 space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5 font-medium">
              <Gauge className="h-4 w-4 text-indigo-400" />
              {metricsText.averageTitle}
            </span>
            <span className="text-[11px] text-indigo-400 font-mono">{metricsText.averageTag}</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-100 font-mono tracking-tight">
              {formatLoadMW(avgLoad, locale)}
            </span>
            <span className="text-xs text-slate-400">MW</span>
          </div>
          <p className="text-[11px] text-slate-500">
            {metricsText.averageNote}
          </p>
        </CardContent>
      </Card>

      {/* Minimum Load (Valley) Card */}
      <Card className="border-slate-800 bg-slate-900/70">
        <CardContent className="p-5 space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5 font-medium">
              <Activity className="h-4 w-4 text-emerald-400" />
              {metricsText.valleyTitle}
            </span>
            <span className="text-[11px] text-emerald-400 font-mono">{metricsText.valleyTag}</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-100 font-mono tracking-tight">
              {formatLoadMW(minLoad, locale)}
            </span>
            <span className="text-xs text-slate-400">MW</span>
          </div>
          <p className="text-[11px] text-slate-500">
            {metricsText.peakValleySpread(formatLoadMW(peakLoad - minLoad, locale))}
          </p>
        </CardContent>
      </Card>

      {/* Max Temperature Card */}
      <Card className="border-amber-500/20 bg-gradient-to-br from-slate-900 via-slate-900 to-amber-950/30">
        <CardContent className="p-5 space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5 font-medium">
              <ThermometerSun className="h-4 w-4 text-amber-400" />
              {metricsText.maxTemperatureTitle}
            </span>
            <span className="text-[11px] text-amber-400 font-mono">{metricsText.maxTemperatureTag}</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-100 font-mono tracking-tight">
              {formatTemperature(maxTemp, locale)}
            </span>
            <span className="text-xs text-slate-400">{metricsText.celsius}</span>
          </div>
          <p className="text-[11px] text-slate-500">
            {metricsText.temperatureNote}
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
