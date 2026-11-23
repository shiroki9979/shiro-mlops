import { useState } from 'react'
import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { DatasetStatusCard } from '@/components/data-explorer/status-card'
import { toQueryView } from '@shiro-mlops/shared/query-view'
import { useDatasetStatus } from '@/hooks/use-data-explorer'
import { Database } from 'lucide-react'
import { useMessages } from '@/i18n/messages'

export const dataRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/data',
  component: DataExplorerOverview,
})

function DataExplorerOverview() {
  const view = toQueryView(useDatasetStatus(), { policy: 'data-first' })
  const m = useMessages()
  // Fixed on entry so re-renders and refetches keep every card on the same 24 hours.
  const [now] = useState(() => new Date())

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
          <Database className="h-5 w-5 text-cyan-400" />
          {m.explorer.title}
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          {m.explorer.overviewDescription} {m.explorer.timeZoneNote}
        </p>
      </div>
      {view.kind === 'loading' && <p className="text-xs text-slate-500">{m.explorer.loadingStatus}</p>}
      {/* The status query is never disabled; 'disabled' is listed only so every kind is handled. */}
      {(view.kind === 'error' || view.kind === 'paused' || view.kind === 'disabled') && (
        <p className="text-xs text-rose-300">{m.explorer.statusError}</p>
      )}
      {view.kind === 'content' && (
        <>
          {view.refreshFailed && <p className="text-xs text-amber-300">{m.explorer.statusRefreshFailed}</p>}
          <div className="grid gap-4 md:grid-cols-2">
            {view.content.datasets.map((status) => (
              <DatasetStatusCard key={status.id} status={status} now={now} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
