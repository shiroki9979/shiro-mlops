import { apiClient } from '@/lib/api-client'
import { PredictionRequest } from '@/schemas/api'
import { useDashboardStore } from '@/store/dashboard-store'
import { useQuery } from '@tanstack/react-query'

export function usePrediction(paramsOverride?: Partial<PredictionRequest>) {
  const { horizonHours, location, autoRefresh, refreshIntervalSec } = useDashboardStore()

  const params: PredictionRequest = {
    horizon_hours: paramsOverride?.horizon_hours ?? horizonHours,
    location: paramsOverride?.location ?? location,
  }

  return useQuery({
    queryKey: ['prediction', params],
    queryFn: () => apiClient.predict(params),
    refetchInterval: autoRefresh ? refreshIntervalSec * 1000 : false,
    staleTime: 60000,
    retry: 2,
  })
}
