import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { useLatestIssuedForecast } from '@/hooks/use-latest-issued-forecast'
import { stepsWithinHorizon } from '@/lib/horizon-window'
import { useDashboardStore } from '@/store/dashboard-store'
import { ForecastChart } from '@/components/dashboard/forecast-chart'
import { HorizonControls } from '@/components/dashboard/horizon-controls'
import { MetricCards } from '@/components/dashboard/metric-cards'
import { ForecastTable } from '@/components/dashboard/forecast-table'
import { OverviewLoading } from '@/components/dashboard/overview-loading'
import { AlertTriangle, CalendarClock, Clock, Inbox } from 'lucide-react'
import { formatDateTime } from '@shiro-mlops/shared/i18n/format'
import { emptyBecause, isNonEmpty, toQueryView } from '@shiro-mlops/shared/query-view'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'
import { isPublishedTimestampStale, STALE_AFTER_HOURS } from '@/lib/published'
import type { LatestIssuedForecast } from '@/schemas/published'

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: OverviewPage,
})

function settleForecast(forecast: LatestIssuedForecast, horizonHours: number) {
  const issuedAt = forecast.issued_at
  // No forecast issued yet: decided by the JSON content alone, never by an HTTP status.
  if (issuedAt === null) return emptyBecause({ kind: 'notIssued' })
  const steps = stepsWithinHorizon(issuedAt, forecast.steps, horizonHours)
  // An issued forecast can cover fewer than 168 hours, down to none, or none within the preset
  // (data contract §6.1).
  return isNonEmpty(steps) ? { issuedAt, steps } : emptyBecause({ kind: 'noStepsInHorizon', issuedAt })
}

function overviewView(forecast: ReturnType<typeof useLatestIssuedForecast>, horizonHours: number) {
  // A failed background refetch keeps the forecast already on screen (forecast-view-hosting §4).
  return toQueryView(forecast, { policy: 'data-first', settle: (data) => settleForecast(data, horizonHours) })
}

type OverviewView = ReturnType<typeof overviewView>

function issuedAtOf(view: OverviewView): string | null {
  if (view.kind === 'content') return view.content.issuedAt
  if (view.kind === 'empty' && view.reason.kind === 'noStepsInHorizon') return view.reason.issuedAt
  return null
}

// Exported so the integration test renders the real page rather than a hand-assembled copy.
export function OverviewPage() {
  const forecast = useLatestIssuedForecast()
  const { horizonHours } = useDashboardStore()
  const m = useMessages()
  const locale = useLocale()

  const view = overviewView(forecast, horizonHours)
  const issuedAt = issuedAtOf(view)

  return (
    <div className="space-y-6">
      {issuedAt !== null && (
        <p className="flex items-center gap-1.5 text-xs text-slate-400">
          <CalendarClock className="h-3.5 w-3.5 text-cyan-400" />
          {m.dashboard.issuedAt(formatDateTime(issuedAt, locale))}
        </p>
      )}

      {/* Neutral on purpose: never says or hints why the forecast is old (ADR-0015 §2.5). */}
      {issuedAt !== null && isPublishedTimestampStale(issuedAt) && (
        <p className="flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          <Clock className="h-3.5 w-3.5 shrink-0 text-amber-400" />
          {m.dashboard.stale(STALE_AFTER_HOURS)}
        </p>
      )}

      <HorizonControls />

      <OverviewBody view={view} horizonHours={horizonHours} />
    </div>
  )
}

function OverviewBody({ view, horizonHours }: { view: OverviewView; horizonHours: number }) {
  const m = useMessages()
  switch (view.kind) {
    case 'loading':
      return <OverviewLoading />
    // Every failure looks the same, whatever the status code or cause; so does a browser offline
    // before the first read (forecast-view-hosting §4).
    case 'error':
    case 'paused':
    case 'disabled':
      return (
        <div
          role="alert"
          className="flex flex-col items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-10 text-center text-sm text-rose-200"
        >
          <AlertTriangle className="h-6 w-6 text-rose-400" />
          <p>{m.dashboard.unavailable}</p>
        </div>
      )
    case 'empty':
      return (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-10 text-center text-sm text-slate-400">
          <Inbox className="h-6 w-6 text-slate-500" />
          <p>{view.reason.kind === 'notIssued' ? m.dashboard.empty : m.dashboard.noStepsInHorizon}</p>
        </div>
      )
    case 'content':
      return (
        <>
          <MetricCards steps={view.content.steps} />
          <ForecastChart steps={view.content.steps} />
          {/* Keyed by preset so a shorter window never opens on a page past its end. */}
          <ForecastTable key={horizonHours} steps={view.content.steps} issuedAt={view.content.issuedAt} />
        </>
      )
  }
}
