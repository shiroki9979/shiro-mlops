import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { DatasetStatusCard } from '@/components/data-explorer/status-card'
import { useDatasetStatus } from '@/hooks/use-data-explorer'
import { Database } from 'lucide-react'
import { useMessages } from '@/i18n/use-messages'

export const dataRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/data',
  component: DataExplorerOverview,
})

function DataExplorerOverview() {
  const { data, isLoading, isError } = useDatasetStatus()
  const m = useMessages()

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
      {isLoading && <p className="text-xs text-slate-500">{m.explorer.loadingStatus}</p>}
      {isError && <p className="text-xs text-rose-300">{m.explorer.statusError}</p>}
      <div className="grid gap-4 md:grid-cols-2">
        {data?.datasets.map((status) => (
          <DatasetStatusCard key={status.id} status={status} />
        ))}
      </div>
    </div>
  )
}
