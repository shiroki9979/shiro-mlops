import { formatDateTime } from '@shiro-mlops/shared/i18n/format'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { Skeleton } from '@shiro-mlops/shared/ui/skeleton'
import { Lead24SeriesChart } from './lead-24-series-chart'
import { LeadTimeCurve } from './lead-time-curve'
import { TrackRecordMetrics } from './track-record-metrics'
import { useForecastTrackRecord } from '@/hooks/use-forecast-track-record'
import { useMessages } from '@/i18n/messages'
import { isPublishedTimestampStale } from '@/lib/published'
import type { ForecastTrackRecord } from '@/schemas/published'

// The page state depends only on the JSON contents, never on an HTTP status (forecast-view-hosting §4).
// Data already loaded wins over a failed background read.
export function TrackRecordContent() {
  const m = useMessages()
  const { data, isError } = useForecastTrackRecord()
  if (data) return <TrackRecord trackRecord={data} />
  if (isError) return <p className="text-sm text-slate-400">{m.history.loadError}</p>
  return <TrackRecordSkeleton />
}

function TrackRecord({ trackRecord }: { trackRecord: ForecastTrackRecord }) {
  const m = useMessages()
  const locale = useLocale()
  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-400">{m.history.cutoff(formatDateTime(trackRecord.cutoff, locale))}</p>
      {/* Neutral and without a reason: the content below stays visible. */}
      {isPublishedTimestampStale(trackRecord.cutoff) && (
        <p className="text-xs text-amber-300">{m.history.staleHint}</p>
      )}
      {trackRecord.metrics ? (
        <>
          <TrackRecordMetrics lead24={trackRecord.metrics.lead_24} />
          <LeadTimeCurve curve={trackRecord.metrics.lead_time_curve} />
          <Lead24SeriesChart series={trackRecord.metrics.lead_24_series} />
        </>
      ) : (
        // Fewer than 7 days accumulated: a neutral empty state, 0 days included.
        <p className="text-sm text-slate-300">{m.history.accumulatedDays(trackRecord.accumulated_days)}</p>
      )}
    </div>
  )
}

function TrackRecordSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true">
      <Skeleton className="h-4 w-48" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
      </div>
    </div>
  )
}
