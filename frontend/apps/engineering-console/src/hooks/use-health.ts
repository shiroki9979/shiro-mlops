import { apiClient } from '@/lib/api-client'
import type { HealthResponse } from '@/schemas/api'
import { type QueryResultLike, toQueryView } from '@shiro-mlops/shared/query-view'
import { useQuery } from '@tanstack/react-query'

export function useHealth(refetchInterval = 30000) {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => apiClient.getHealth(),
    refetchInterval,
    retry: 1,
  })
}

export type ServiceState =
  | { kind: 'healthy'; health: HealthResponse }
  | { kind: 'modelNotLoaded' }
  | { kind: 'unreachable' }
  | { kind: 'checking' }

// The header badge and the sidebar status card both state the API's condition now, so a failed or
// offline read outranks the last response, and both read it from here so they never disagree.
export function serviceStateOf(healthQuery: QueryResultLike<HealthResponse>): ServiceState {
  const view = toQueryView(healthQuery, { policy: 'error-first' })
  switch (view.kind) {
    case 'content':
      return view.content.model_loaded ? { kind: 'healthy', health: view.content } : { kind: 'modelNotLoaded' }
    case 'error':
    case 'paused':
      return { kind: 'unreachable' }
    case 'loading':
    case 'disabled':
      return { kind: 'checking' }
  }
}
