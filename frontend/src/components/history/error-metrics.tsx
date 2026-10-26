import { Card, CardContent } from '@/components/ui/card'
import { Award, CheckCircle2, Percent, Target } from 'lucide-react'
import { useMessages } from '@/i18n/use-messages'

export function ErrorMetrics() {
  const text = useMessages().history.metrics
  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
      <Card className="border-emerald-500/20 bg-slate-900/70">
        <CardContent className="p-5 space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <Percent className="h-4 w-4 text-emerald-400" />
              {text.mape}
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-emerald-400">2.14%</span>
            <span className="text-xs text-emerald-500/80 font-medium">{text.mapeBaseline}</span>
          </div>
          <p className="text-[11px] text-slate-500">{text.mapeNote}</p>
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/70">
        <CardContent className="p-5 space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <Target className="h-4 w-4 text-cyan-400" />
              {text.rmse}
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-cyan-300">412.8</span>
            <span className="text-xs text-slate-400">MW</span>
          </div>
          <p className="text-[11px] text-slate-500">{text.rmseNote}</p>
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/70">
        <CardContent className="p-5 space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <Award className="h-4 w-4 text-indigo-400" />
              {text.mae}
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-indigo-300">328.5</span>
            <span className="text-xs text-slate-400">MW</span>
          </div>
          <p className="text-[11px] text-slate-500">{text.maeNote}</p>
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/70">
        <CardContent className="p-5 space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <CheckCircle2 className="h-4 w-4 text-amber-400" />
              {text.peakHitRate}
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-amber-300">96.8%</span>
          </div>
          <p className="text-[11px] text-slate-500">{text.peakHitRateNote}</p>
        </CardContent>
      </Card>
    </div>
  )
}
