import { useId, type ReactNode } from 'react'
import { Card, CardContent } from '@shiro-mlops/shared/ui/card'
import { Award, Percent } from 'lucide-react'
import { EMPTY_VALUE, formatLoadMW, formatPercent } from '@shiro-mlops/shared/i18n/format'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'
import type { LeadTimeMetrics } from '@/schemas/published'

const MAPE_FRACTION_DIGITS = 2

// The headline numbers stay at lead time 24 h, the day-ahead convention (ADR-0013 §2.3).
export function TrackRecordMetrics({ lead24 }: { lead24: LeadTimeMetrics }) {
  const locale = useLocale()
  const metricsText = useMessages().history.metrics
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <MetricCard
        icon={<Percent className="h-4 w-4 text-emerald-400" />}
        label={metricsText.lead24Mape}
        value={lead24.mape === null ? EMPTY_VALUE : formatPercent(lead24.mape, locale, MAPE_FRACTION_DIGITS)}
        valueClassName="text-emerald-400"
      />
      <MetricCard
        icon={<Award className="h-4 w-4 text-indigo-400" />}
        label={metricsText.lead24Mae}
        value={lead24.mae === null ? EMPTY_VALUE : formatLoadMW(lead24.mae, locale)}
        unit="MW"
        valueClassName="text-indigo-300"
      />
    </div>
  )
}

interface MetricCardProps {
  icon: ReactNode
  label: string
  value: string
  unit?: string
  valueClassName: string
}

function MetricCard({ icon, label, value, unit, valueClassName }: MetricCardProps) {
  const labelId = useId()
  return (
    <Card role="group" aria-labelledby={labelId} className="border-slate-800 bg-slate-900/70">
      <CardContent className="p-5 space-y-1">
        <div className="flex items-center gap-1.5 text-xs text-slate-400">
          {icon}
          <span id={labelId}>{label}</span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className={`text-2xl font-bold font-mono ${valueClassName}`}>{value}</span>
          {unit && <span className="text-xs text-slate-400">{unit}</span>}
        </div>
      </CardContent>
    </Card>
  )
}
