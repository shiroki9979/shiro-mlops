import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { usePrediction } from '@/hooks/use-prediction'
import { ForecastChart } from '@/components/dashboard/forecast-chart'
import { HorizonControls } from '@/components/dashboard/horizon-controls'
import { MetricCards } from '@/components/dashboard/metric-cards'
import { PredictionTable } from '@/components/dashboard/prediction-table'
import { AlertTriangle } from 'lucide-react'

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: OverviewPage,
})

function OverviewPage() {
  const { data, isLoading, isError, error } = usePrediction()

  return (
    <div className="space-y-6">
      {/* Degraded mode / Error banner */}
      {isError && (
        <div className="flex items-center gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-300">
          <AlertTriangle className="h-5 w-5 shrink-0 text-rose-400" />
          <div>
            <p className="font-semibold text-rose-200">
              無法取得即時推論資料 (Inference Service Error)
            </p>
            <p className="text-rose-300/80">
              {error instanceof Error ? error.message : '請檢查後端 API 是否已啟動 (make dev)'}
            </p>
          </div>
        </div>
      )}

      {/* Horizon & Filter Controls */}
      <HorizonControls />

      {/* Metric Cards */}
      <MetricCards predictions={data?.predictions} isLoading={isLoading} />

      {/* Dual Axis Interactive Chart */}
      <ForecastChart predictions={data?.predictions} isLoading={isLoading} />

      {/* Hourly Detail Table */}
      <PredictionTable
        predictions={data?.predictions}
        isLoading={isLoading}
        subject={data?.subject}
      />
    </div>
  )
}
