import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient, type DataExplorerError, type QueryParams } from '@/lib/api-client'
import type { ListEnvelope, SeriesResponse } from '@/schemas/data-explorer'

function retryOnceWhenDatabaseUnavailable(failureCount: number, error: DataExplorerError): boolean {
  return failureCount < 1 && error.kind === 'databaseUnavailable'
}

const DATASET_STATUS_QUERY_KEY = ['data-explorer', 'status'] as const

export function useDatasetStatus() {
  return useQuery({
    queryKey: DATASET_STATUS_QUERY_KEY,
    queryFn: () => apiClient.getDataStatus(),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}

// The status never goes stale on its own (manual Refresh only), so pages without a Refresh of
// their own rely on the header's: it re-reads the status wherever a page is showing it.
export function useRefetchDatasetStatus() {
  const queryClient = useQueryClient()
  return () => queryClient.refetchQueries({ queryKey: DATASET_STATUS_QUERY_KEY, type: 'active' })
}

export function datasetListQueryKey(path: string, params: Record<string, string | undefined>) {
  return ['data-explorer', path, params] as const
}

export function useDatasetList(
  path: string,
  params: Record<string, string | undefined>,
  enabled = true,
) {
  return useQuery<ListEnvelope, DataExplorerError>({
    queryKey: datasetListQueryKey(path, params),
    queryFn: () => apiClient.getDataList(path, params),
    enabled,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: retryOnceWhenDatabaseUnavailable,
  })
}

export function datasetSeriesQueryKey(path: string, params: QueryParams) {
  return ['data-explorer', 'series', path, params] as const
}

export function useDatasetSeries(path: string, params: QueryParams, enabled = true) {
  return useQuery<SeriesResponse, DataExplorerError>({
    queryKey: datasetSeriesQueryKey(path, params),
    queryFn: () => apiClient.getDataSeries(path, params),
    enabled,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: retryOnceWhenDatabaseUnavailable,
  })
}

// Refresh re-reads whichever chart the page shows without knowing its series parameters.
export function useRefetchDatasetSeries() {
  const queryClient = useQueryClient()
  return (path: string) => queryClient.refetchQueries({ queryKey: ['data-explorer', 'series', path], type: 'active' })
}
