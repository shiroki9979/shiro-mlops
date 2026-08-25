import { Card, CardContent } from '@/components/ui/card'
import { Award, CheckCircle2, Percent, Target } from 'lucide-react'

export function ErrorMetrics() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
      <Card className="border-emerald-500/20 bg-slate-900/70">
        <CardContent className="p-5 space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <Percent className="h-4 w-4 text-emerald-400" />
              MAPE (平均絕對百分比誤差)
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-emerald-400">2.14%</span>
            <span className="text-xs text-emerald-500/80 font-medium">優於基準 (&lt;3.5%)</span>
          </div>
          <p className="text-[11px] text-slate-500">最近 7 天滾動回測評估</p>
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/70">
        <CardContent className="p-5 space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <Target className="h-4 w-4 text-cyan-400" />
              RMSE (均方根誤差)
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-cyan-300">412.8</span>
            <span className="text-xs text-slate-400">MW</span>
          </div>
          <p className="text-[11px] text-slate-500">整體偏差控制在合理區間</p>
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/70">
        <CardContent className="p-5 space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <Award className="h-4 w-4 text-indigo-400" />
              MAE (平均絕對誤差)
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-indigo-300">328.5</span>
            <span className="text-xs text-slate-400">MW</span>
          </div>
          <p className="text-[11px] text-slate-500">平均絕對偏差值</p>
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/70">
        <CardContent className="p-5 space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <CheckCircle2 className="h-4 w-4 text-amber-400" />
              尖峰預測命中率 (Top 5%)
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-amber-300">96.8%</span>
          </div>
          <p className="text-[11px] text-slate-500">尖峰時段高準確度預警</p>
        </CardContent>
      </Card>
    </div>
  )
}
