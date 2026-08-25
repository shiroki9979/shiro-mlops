import { apiClient } from '@/lib/api-client'
import { useQuery } from '@tanstack/react-query'

export function useLatestFeatures(limit = 24) {
  return useQuery({
    queryKey: ['features', 'latest', limit],
    queryFn: () => apiClient.getLatestFeatures(limit),
    staleTime: 60000,
    retry: 1,
  })
}
