import { Card, CardContent } from '@/components/ui/card'
import { Award, CheckCircle2, Percent, Target } from 'lucide-react'
import { formatLoadMW, formatPercent } from '@/i18n/format'
import { useLocale } from '@/i18n/locale-store'
import { useMessages } from '@/i18n/use-messages'

// Fixed demo figures until the page reads real evaluation results; formatted at render so they follow the locale.
const DEMO_METRICS = {
  mapePercent: 2.14,
  rmseMW: 412.8,
  maeMW: 328.5,
  peakHitRatePercent: 96.8,
}

const MAPE_FRACTION_DIGITS = 2
const HIT_RATE_FRACTION_DIGITS = 1

export function ErrorMetrics() {
  const locale = useLocale()
  const metricsText = useMessages().history.metrics
  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
      <Card className="border-emerald-500/20 bg-slate-900/70">
        <CardContent className="p-5 space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <Percent className="h-4 w-4 text-emerald-400" />
              {metricsText.mape}
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-emerald-400">
              {formatPercent(DEMO_METRICS.mapePercent, locale, MAPE_FRACTION_DIGITS)}
            </span>
            <span className="text-xs text-emerald-500/80 font-medium">{metricsText.mapeBaseline}</span>
          </div>
          <p className="text-[11px] text-slate-500">{metricsText.mapeNote}</p>
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/70">
        <CardContent className="p-5 space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <Target className="h-4 w-4 text-cyan-400" />
              {metricsText.rmse}
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-cyan-300">
              {formatLoadMW(DEMO_METRICS.rmseMW, locale)}
            </span>
            <span className="text-xs text-slate-400">MW</span>
          </div>
          <p className="text-[11px] text-slate-500">{metricsText.rmseNote}</p>
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/70">
        <CardContent className="p-5 space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <Award className="h-4 w-4 text-indigo-400" />
              {metricsText.mae}
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-indigo-300">
              {formatLoadMW(DEMO_METRICS.maeMW, locale)}
            </span>
            <span className="text-xs text-slate-400">MW</span>
          </div>
          <p className="text-[11px] text-slate-500">{metricsText.maeNote}</p>
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/70">
        <CardContent className="p-5 space-y-1">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <CheckCircle2 className="h-4 w-4 text-amber-400" />
              {metricsText.peakHitRate}
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-amber-300">
              {formatPercent(DEMO_METRICS.peakHitRatePercent, locale, HIT_RATE_FRACTION_DIGITS)}
            </span>
          </div>
          <p className="text-[11px] text-slate-500">{metricsText.peakHitRateNote}</p>
        </CardContent>
      </Card>
    </div>
  )
}
