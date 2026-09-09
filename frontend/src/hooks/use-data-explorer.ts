import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

export function useDatasetStatus() {
  return useQuery({
    queryKey: ['data-explorer', 'status'],
    queryFn: () => apiClient.getDataStatus(),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}

export function useDatasetList(
  path: string,
  params: Record<string, string | undefined>,
  enabled = true,
) {
  return useQuery({
    queryKey: ['data-explorer', path, params],
    queryFn: () => apiClient.getDataList(path, params),
    enabled,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
