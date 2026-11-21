import { apiClient } from '@/lib/api-client'
import { useQuery } from '@tanstack/react-query'

export function useHealth(refetchInterval = 30000) {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => apiClient.getHealth(),
    refetchInterval,
    retry: 1,
  })
}
