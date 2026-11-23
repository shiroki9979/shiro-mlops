import { useMemo } from 'react'
import { useNavigate, useRouterState } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { datasetListQueryKey, useDatasetList } from '@/hooks/use-data-explorer'
import { defaultWindow, toRfc3339 } from '@/lib/data-explorer'
import type { ExplorerWindow } from '@/lib/explorer-window'
import type { ExplorerDatasetConfig, ExplorerFieldKey } from './catalog'
import {
  backToFirstPage,
  changeChart,
  changeFilter,
  changeWindow,
  type ChartSettingsPatch,
  type ExplorerQueryState,
  isWithinDetailLimit,
  listRequest,
  nextPage,
  parseExplorerQuery,
  seriesRequest,
  toExplorerSearch,
} from './explorer-query-state'

export function useExplorerQuery(dataset: ExplorerDatasetConfig) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const search = useRouterState().location.search as Record<string, unknown>
  const state = parseExplorerQuery(dataset, search, useDefaultWindow(dataset))
  const request = isWithinDetailLimit(state) ? listRequest(state) : undefined
  const list = useDatasetList(dataset.apiPath, request ?? {}, request !== undefined)

  const navigateTo = (next: ExplorerQueryState) => {
    void navigate({ to: dataset.path as never, search: toExplorerSearch(dataset, next) as never })
  }

  // The recovered first page may already be cached from before paging; evict it so the user sees current rows.
  const restartFromFirstPage = () => {
    if (!isWithinDetailLimit(state)) return
    const firstPage = backToFirstPage(state)
    queryClient.removeQueries({ queryKey: datasetListQueryKey(dataset.apiPath, listRequest(firstPage)), exact: true })
    navigateTo(firstPage)
  }

  return {
    state,
    listRequest: request,
    series: seriesRequest(dataset, state),
    list,
    setStart: (value: string) => navigateTo(changeWindow(dataset, state, { start: value })),
    setEnd: (value: string) => navigateTo(changeWindow(dataset, state, { end: value })),
    // Quick ranges and shifts replace both ends in one navigation so no half-moved window is fetched.
    setWindow: (window: ExplorerWindow) => navigateTo(changeWindow(dataset, state, window)),
    setFilter: (key: ExplorerFieldKey, value: string | boolean) => navigateTo(changeFilter(state, key, value)),
    goToNextPage: (cursor: string | undefined) => {
      if (cursor && isWithinDetailLimit(state)) navigateTo(nextPage(state, cursor))
    },
    restartFromFirstPage,
    setChart: (patch: ChartSettingsPatch) => navigateTo(changeChart(dataset, state, patch)),
    refetchList: () => {
      if (request) void list.refetch()
    },
  }
}

// Computed once per page visit so re-renders (e.g. opening a detail) do not slide an implicit window.
function useDefaultWindow(dataset: ExplorerDatasetConfig): ExplorerWindow {
  return useMemo(() => {
    const range = defaultWindow(dataset.defaultHours, dataset.lookAheadHours ?? 0)
    return { start: toRfc3339(range.start), end: toRfc3339(range.end) }
  }, [dataset.defaultHours, dataset.lookAheadHours])
}
