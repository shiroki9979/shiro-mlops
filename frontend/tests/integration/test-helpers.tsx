import React from 'react'
import { usePrediction } from '@/hooks/use-prediction'
import { useDashboardStore } from '@/store/dashboard-store'
import { HorizonControls } from '@/components/dashboard/horizon-controls'
import { MetricCards } from '@/components/dashboard/metric-cards'
import { PredictionTable } from '@/components/dashboard/prediction-table'

export function OverviewPageForTest() {
  const { location } = useDashboardStore()
  const { data, isLoading } = usePrediction()

  return (
    <div className="space-y-6">
      <HorizonControls />
      <MetricCards predictions={data?.predictions} isLoading={isLoading} />
      <PredictionTable
        predictions={data?.predictions}
        isLoading={isLoading}
        location={location}
      />
    </div>
  )
}
