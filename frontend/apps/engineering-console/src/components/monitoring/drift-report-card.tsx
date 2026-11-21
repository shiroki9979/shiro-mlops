import { Badge } from '@shiro-mlops/shared/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import { AlertCircle, CheckCircle2, ShieldCheck } from 'lucide-react'
import { formatDecimal, formatNumber } from '@shiro-mlops/shared/i18n/format'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { type Messages, useMessages } from '@/i18n/messages'

type DriftText = Messages['monitoring']['drift']

const DRIFT_SCORE_FRACTION_DIGITS = 3

// Demo data: feature names are code identifiers (kept verbatim); descriptions come from the dictionary.
const DRIFT_METRICS: Array<{
  feature: string
  descriptionKey: keyof DriftText['features']
  driftScore: number
  threshold: number
  status: 'NORMAL' | 'WARNING'
  statTest: keyof DriftText['tests']
}> = [
  {
    feature: 'temperature_north',
    descriptionKey: 'temperatureNorth',
    driftScore: 0.032,
    threshold: 0.1,
    status: 'NORMAL',
    statTest: 'wasserstein',
  },
  {
    feature: 'relative_humidity',
    descriptionKey: 'relativeHumidity',
    driftScore: 0.048,
    threshold: 0.1,
    status: 'NORMAL',
    statTest: 'wasserstein',
  },
  {
    feature: 'load_lag_24h',
    descriptionKey: 'loadLag24h',
    driftScore: 0.088,
    threshold: 0.1,
    status: 'WARNING',
    statTest: 'psi',
  },
  {
    feature: 'load_rolling_mean_7d',
    descriptionKey: 'loadRollingMean7d',
    driftScore: 0.021,
    threshold: 0.1,
    status: 'NORMAL',
    statTest: 'wasserstein',
  },
  {
    feature: 'is_weekend / is_holiday',
    descriptionKey: 'calendarFlags',
    driftScore: 0.005,
    threshold: 0.05,
    status: 'NORMAL',
    statTest: 'chiSquare',
  },
]

export function DriftReportCard() {
  const locale = useLocale()
  const driftText = useMessages().monitoring.drift
  return (
    <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div>
          <CardTitle className="text-base font-semibold text-slate-200 flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-cyan-400" />
            {driftText.title}
          </CardTitle>
          <p className="text-xs text-slate-400 mt-1">
            {driftText.description}
          </p>
        </div>
        <Badge variant="success" className="gap-1.5 py-1 px-3">
          <CheckCircle2 className="h-3.5 w-3.5" />
          {driftText.overall}
        </Badge>
      </CardHeader>
      <CardContent>
        <div className="divide-y divide-slate-800/80">
          {DRIFT_METRICS.map((item, idx) => (
            <div
              key={idx}
              className="py-3.5 flex items-center justify-between text-xs"
            >
              <div className="space-y-1">
                <p className="font-mono font-semibold text-slate-200">
                  {item.feature} ({driftText.features[item.descriptionKey]})
                </p>
                <p className="text-[11px] text-slate-500">
                  {driftText.testAndThreshold(driftText.tests[item.statTest], formatNumber(item.threshold, locale))}
                </p>
              </div>

              <div className="flex items-center gap-4">
                <div className="text-right">
                  <span className="font-mono font-bold text-slate-200">
                    {formatDecimal(item.driftScore, locale, DRIFT_SCORE_FRACTION_DIGITS)}
                  </span>
                  <p className="text-[10px] text-slate-500">{driftText.scoreLabel}</p>
                </div>
                {item.status === 'NORMAL' ? (
                  <Badge variant="success" className="text-[10px]">
                    <CheckCircle2 className="h-3 w-3 mr-1" />
                    {driftText.normal}
                  </Badge>
                ) : (
                  <Badge variant="warning" className="text-[10px]">
                    <AlertCircle className="h-3 w-3 mr-1" />
                    {driftText.warning}
                  </Badge>
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
