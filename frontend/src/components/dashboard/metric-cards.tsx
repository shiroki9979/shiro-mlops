import { PredictionItem } from '@/schemas/api'
import { Card, CardContent } from '@/components/ui/card'
import { formatLoadMW, formatTemperature } from '@/lib/utils'
import { Activity, ArrowUpRight, Gauge, ThermometerSun, Zap } from 'lucide-react'

interface MetricCardsProps {
  predictions?: PredictionItem[]
  isLoading: boolean
}

export function MetricCards({ predictions, isLoading }: MetricCardsProps) {
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
              尖峰用電預估
            </span>
            <span className="flex items-center text-cyan-400 text-[11px]">
              Peak <ArrowUpRight className="h-3 w-3" />
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-100 font-mono tracking-tight">
              {formatLoadMW(peakLoad)}
            </span>
            <span className="text-xs text-slate-400">MW</span>
          </div>
          <p className="text-[11px] text-slate-500 truncate">
            預計發生時間：{peakItem ? new Date(peakItem.datetime).toLocaleString('zh-TW', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '--'}
          </p>
        </CardContent>
      </Card>

      {/* Average Load Card */}
      <Card className="border-slate-800 bg-slate-900/70">
        <CardContent className="p-5 space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5 font-medium">
              <Gauge className="h-4 w-4 text-indigo-400" />
              區間平均負載
            </span>
            <span className="text-[11px] text-indigo-400 font-mono">AVG</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-100 font-mono tracking-tight">
              {formatLoadMW(avgLoad)}
            </span>
            <span className="text-xs text-slate-400">MW</span>
          </div>
          <p className="text-[11px] text-slate-500">
            預測區間負載平穩度指標
          </p>
        </CardContent>
      </Card>

      {/* Minimum Load (Valley) Card */}
      <Card className="border-slate-800 bg-slate-900/70">
        <CardContent className="p-5 space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5 font-medium">
              <Activity className="h-4 w-4 text-emerald-400" />
              離峰用電低谷
            </span>
            <span className="text-[11px] text-emerald-400 font-mono">VALLEY</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-100 font-mono tracking-tight">
              {formatLoadMW(minLoad)}
            </span>
            <span className="text-xs text-slate-400">MW</span>
          </div>
          <p className="text-[11px] text-slate-500">
            尖離峰負載差：{formatLoadMW(peakLoad - minLoad)} MW
          </p>
        </CardContent>
      </Card>

      {/* Max Temperature Card */}
      <Card className="border-amber-500/20 bg-gradient-to-br from-slate-900 via-slate-900 to-amber-950/30">
        <CardContent className="p-5 space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5 font-medium">
              <ThermometerSun className="h-4 w-4 text-amber-400" />
              最高預估氣溫
            </span>
            <span className="text-[11px] text-amber-400 font-mono">CWA WX</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-100 font-mono tracking-tight">
              {formatTemperature(maxTemp)}
            </span>
            <span className="text-xs text-slate-400">攝氏度</span>
          </div>
          <p className="text-[11px] text-slate-500">
            溫度敏感度加權分析
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
