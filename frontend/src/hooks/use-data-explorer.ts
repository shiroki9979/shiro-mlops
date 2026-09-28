import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'

function shouldRetryListQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= 1 || typeof error !== 'object' || error === null || !('status' in error)) {
    return false
  }
  return error.status === 503
}

export function useDatasetStatus() {
  return useQuery({
    queryKey: ['data-explorer', 'status'],
    queryFn: () => apiClient.getDataStatus(),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}

export function datasetListQueryKey(path: string, params: Record<string, string | undefined>) {
  return ['data-explorer', path, params] as const
}

export function useDatasetList(
  path: string,
  params: Record<string, string | undefined>,
  enabled = true,
) {
  return useQuery({
    queryKey: datasetListQueryKey(path, params),
    queryFn: () => apiClient.getDataList(path, params),
    enabled,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: shouldRetryListQuery,
  })
}
