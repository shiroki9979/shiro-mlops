import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { DriftReportCard } from '@/components/monitoring/drift-report-card'
import { FeatureStoreView } from '@/components/monitoring/feature-store-view'
import { Activity } from 'lucide-react'

export const monitoringRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/monitoring',
  component: MonitoringPage,
})

function MonitoringPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Activity className="h-5 w-5 text-cyan-400" />
            模型資料漂移與特徵監控 (Model Monitoring & Feature Store)
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            整合 Evidently AI 漂移檢定與 Feast Online/Offline 特徵儲存庫快照監控。
          </p>
        </div>
      </div>

      {/* Evidently Drift Report */}
      <DriftReportCard />

      {/* Feast Feature Store Snapshot */}
      <FeatureStoreView />
    </div>
  )
}
