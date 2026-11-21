import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { useLatestIssuedForecast } from '@/hooks/use-latest-issued-forecast'
import { stepsWithinHorizon } from '@/lib/horizon-window'
import { useDashboardStore } from '@/store/dashboard-store'
import { ForecastChart } from '@/components/dashboard/forecast-chart'
import { HorizonControls } from '@/components/dashboard/horizon-controls'
import { MetricCards } from '@/components/dashboard/metric-cards'
import { PredictionTable } from '@/components/dashboard/prediction-table'
import { AlertTriangle, CalendarClock, Clock, Inbox } from 'lucide-react'
import { formatDateTime } from '@shiro-mlops/shared/i18n/format'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'

const STALE_AFTER_MS = 24 * 3_600_000

// Compared against the viewer's clock on render only; no timer re-checks it (ADR-0015 §2.5).
function isStale(issuedAt: string): boolean {
  return Date.now() - Date.parse(issuedAt) > STALE_AFTER_MS
}

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: OverviewPage,
})

// Exported so the integration test renders the real page rather than a hand-assembled copy.
export function OverviewPage() {
  const { data, isPending, isError } = useLatestIssuedForecast()
  const { horizonHours } = useDashboardStore()
  const m = useMessages()
  const locale = useLocale()

  const issuedAt = data?.issued_at ?? null
  const steps = issuedAt === null ? [] : stepsWithinHorizon(issuedAt, data?.steps ?? [], horizonHours)
  // A failed background refetch keeps the forecast already on screen; only a page with nothing loaded
  // shows the error. Every failure looks the same, whatever the status code or cause.
  const unavailable = isError && data === undefined
  // No forecast issued yet: decided by the JSON content alone, never by an HTTP status.
  const notIssued = data !== undefined && issuedAt === null
  // An issued forecast can cover fewer than 168 hours, down to none, or none within the preset
  // (data contract §6.1). The read has finished, so this is a settled view, never a loading one.
  const noStepsInHorizon = issuedAt !== null && steps.length === 0

  return (
    <div className="space-y-6">
      {issuedAt !== null && (
        <p className="flex items-center gap-1.5 text-xs text-slate-400">
          <CalendarClock className="h-3.5 w-3.5 text-cyan-400" />
          {m.dashboard.issuedAt(formatDateTime(issuedAt, locale))}
        </p>
      )}

      {/* Neutral on purpose: never says or hints why the forecast is old (ADR-0015 §2.5). */}
      {issuedAt !== null && isStale(issuedAt) && (
        <p className="flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          <Clock className="h-3.5 w-3.5 shrink-0 text-amber-400" />
          {m.dashboard.stale}
        </p>
      )}

      {/* Horizon & Filter Controls */}
      <HorizonControls />

      {unavailable ? (
        <div
          role="alert"
          className="flex flex-col items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-10 text-center text-sm text-rose-200"
        >
          <AlertTriangle className="h-6 w-6 text-rose-400" />
          <p>{m.dashboard.unavailable}</p>
        </div>
      ) : notIssued ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-10 text-center text-sm text-slate-400">
          <Inbox className="h-6 w-6 text-slate-500" />
          <p>{m.dashboard.empty}</p>
        </div>
      ) : noStepsInHorizon ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-10 text-center text-sm text-slate-400">
          <Inbox className="h-6 w-6 text-slate-500" />
          <p>{m.dashboard.noStepsInHorizon}</p>
        </div>
      ) : (
        <>
          {/* Loading comes from the read alone; once it settles, the steps here are never empty. */}
          {/* Metric Cards */}
          <MetricCards steps={steps} isLoading={isPending} />

          {/* Predicted Load Chart */}
          <ForecastChart steps={steps} isLoading={isPending} />

          {/* Hourly Detail Table; keyed by preset so a shorter window never opens on a page past its end */}
          <PredictionTable key={horizonHours} steps={steps} isLoading={isPending} issuedAt={issuedAt} />
        </>
      )}
    </div>
  )
}
