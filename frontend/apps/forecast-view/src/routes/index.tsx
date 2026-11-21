import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { useLatestIssuedForecast } from '@/hooks/use-latest-issued-forecast'
import { stepsWithinHorizon } from '@/lib/horizon-window'
import { useDashboardStore } from '@/store/dashboard-store'
import { ForecastChart } from '@/components/dashboard/forecast-chart'
import { HorizonControls } from '@/components/dashboard/horizon-controls'
import { MetricCards } from '@/components/dashboard/metric-cards'
import { PredictionTable } from '@/components/dashboard/prediction-table'
import { AlertTriangle, CalendarClock } from 'lucide-react'
import { formatDateTime } from '@shiro-mlops/shared/i18n/format'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: OverviewPage,
})

// Exported so the integration test renders the real page rather than a hand-assembled copy.
export function OverviewPage() {
  const { data, isLoading, isError, error } = useLatestIssuedForecast()
  const { horizonHours } = useDashboardStore()
  const m = useMessages()
  const locale = useLocale()

  const issuedAt = data?.issued_at ?? null
  const steps = issuedAt === null ? undefined : stepsWithinHorizon(issuedAt, data?.steps ?? [], horizonHours)

  return (
    <div className="space-y-6">
      {/* Degraded mode / Error banner */}
      {isError && (
        <div className="flex items-center gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-300">
          <AlertTriangle className="h-5 w-5 shrink-0 text-rose-400" />
          <div>
            <p className="font-semibold text-rose-200">
              {m.dashboard.errorTitle}
            </p>
            <p className="text-rose-300/80">
              {error instanceof Error ? error.message : m.dashboard.errorFallback}
            </p>
          </div>
        </div>
      )}

      {issuedAt !== null && (
        <p className="flex items-center gap-1.5 text-xs text-slate-400">
          <CalendarClock className="h-3.5 w-3.5 text-cyan-400" />
          {m.dashboard.issuedAt(formatDateTime(issuedAt, locale))}
        </p>
      )}

      {/* Horizon & Filter Controls */}
      <HorizonControls />

      {/* Metric Cards */}
      <MetricCards steps={steps} isLoading={isLoading} />

      {/* Predicted Load Chart */}
      <ForecastChart steps={steps} isLoading={isLoading} />

      {/* Hourly Detail Table; keyed by preset so a shorter window never opens on a page past its end */}
      <PredictionTable key={horizonHours} steps={steps} isLoading={isLoading} issuedAt={issuedAt} />
    </div>
  )
}
