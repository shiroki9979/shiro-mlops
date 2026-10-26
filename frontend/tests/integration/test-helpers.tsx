import React from 'react'
import { usePrediction } from '@/hooks/use-prediction'
import { HorizonControls } from '@/components/dashboard/horizon-controls'
import { MetricCards } from '@/components/dashboard/metric-cards'
import { PredictionTable } from '@/components/dashboard/prediction-table'
import { useLocaleStore } from '@/i18n/locale-store'

// jsdom reports en-US as the browser language, so tests pin zh-TW unless a test switches explicitly.
export function resetLocaleForTest() {
  useLocaleStore.setState({ preference: 'zh-TW' })
  localStorage.clear()
}

export function OverviewPageForTest() {
  const { data, isLoading } = usePrediction()

  return (
    <div className="space-y-6">
      <HorizonControls />
      <MetricCards predictions={data?.predictions} isLoading={isLoading} />
      <PredictionTable
        predictions={data?.predictions}
        isLoading={isLoading}
        subject={data?.subject}
      />
    </div>
  )
}
