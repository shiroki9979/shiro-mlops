import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { DriftReportCard } from '@/components/monitoring/drift-report-card'
import { DataSourceStatus } from '@/components/monitoring/data-source-status'
import { Activity } from 'lucide-react'
import { useMessages } from '@/i18n/use-messages'

export const monitoringRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/monitoring',
  component: MonitoringPage,
})

function MonitoringPage() {
  const text = useMessages().monitoring
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Activity className="h-5 w-5 text-cyan-400" />
            {text.title}
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            {text.description}
          </p>
        </div>
      </div>

      <DriftReportCard />
      <DataSourceStatus />
    </div>
  )
}
