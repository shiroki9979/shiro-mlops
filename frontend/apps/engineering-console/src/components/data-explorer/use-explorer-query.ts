import { useMemo } from 'react'
import { useNavigate, useRouterState } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { datasetListQueryKey, useDatasetList } from '@/hooks/use-data-explorer'
import { defaultWindow, toRfc3339 } from '@/lib/data-explorer'
import type { ExplorerDatasetConfig } from './catalog'

type SearchValues = Record<string, string | undefined>

// Chart settings live in the URL beside the window but never reach the list request or its cursor.
export const CHART_SEARCH_KEYS = ['fields', 'group_by', 'bucket', 'agg'] as const
export type ChartSearchKey = (typeof CHART_SEARCH_KEYS)[number]
export type ChartSearch = Partial<Record<ChartSearchKey, string | string[]>>
export const CHART_DEFAULTS: Partial<Record<ChartSearchKey, string>> = { bucket: 'auto', agg: 'avg' }

// A v2 cursor is bound to the window and filters it was issued for, so every change
// other than paging must land on the first page; only paging sets a cursor.
export function useExplorerQuery(dataset: ExplorerDatasetConfig) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const search = useRouterState().location.search as SearchValues
  const fallbackWindow = useDefaultWindow(dataset)
  const start = search.start || fallbackWindow.start
  const end = search.end || fallbackWindow.end
  const filterValues = declaredFilterValues(dataset, search)
  const query: SearchValues = { start, end, ...filterValues }
  const cursor = search.cursor
  const chartSearch = pickChartSearch(search)
  const list = useDatasetList(dataset.apiPath, { ...query, cursor })

  const navigateTo = (nextSearch: Record<string, unknown>) => {
    void navigate({ to: dataset.path as never, search: withoutBlanks(nextSearch) as never })
  }
  const showPage = (nextQuery: SearchValues, nextCursor?: string) => {
    navigateTo({ ...dataset.search, ...nextQuery, ...chartSearch, cursor: nextCursor })
  }
  // A chart setting changes neither the rows nor what the cursor is bound to, so the page stays.
  const setChartSetting = (key: ChartSearchKey, value: string) => {
    const stored = CHART_DEFAULTS[key] === value ? undefined : value
    navigateTo({ ...dataset.search, ...query, ...chartSearch, [key]: stored, cursor })
  }
  const showFirstPageOf = (patch: SearchValues) => showPage({ ...query, ...patch })

  // The recovered first page may already be cached from before paging; evict it so the user sees current rows.
  const restartFromFirstPage = () => {
    queryClient.removeQueries({ queryKey: datasetListQueryKey(dataset.apiPath, query), exact: true })
    showPage(query)
  }

  return {
    start,
    end,
    filterValues,
    query,
    chartSearch,
    list,
    canRestart: Boolean(cursor),
    setStart: (value: string) => showFirstPageOf({ start: value }),
    setEnd: (value: string) => showFirstPageOf({ end: value }),
    setFilter: (key: string, value: string) => showFirstPageOf({ [key]: value }),
    goToNextPage: (nextCursor: string | undefined) => showPage(query, nextCursor),
    restartFromFirstPage,
    setChartSetting,
    refetchList: () => void list.refetch(),
  }
}

// Computed once per page visit so re-renders (e.g. opening a detail) do not slide an implicit window.
function useDefaultWindow(dataset: ExplorerDatasetConfig): { start: string; end: string } {
  return useMemo(() => {
    const range = defaultWindow(dataset.defaultHours, dataset.lookAheadHours ?? 0)
    return { start: toRfc3339(range.start), end: toRfc3339(range.end) }
  }, [dataset.defaultHours, dataset.lookAheadHours])
}

function declaredFilterValues(dataset: ExplorerDatasetConfig, search: SearchValues): SearchValues {
  return Object.fromEntries(dataset.filters.map((field) => [field.key, search[field.key]]))
}

function pickChartSearch(search: Record<string, unknown>): ChartSearch {
  return Object.fromEntries(
    CHART_SEARCH_KEYS.filter((key) => search[key] !== undefined).map((key) => [key, search[key]]),
  ) as ChartSearch
}

// Blank values fall back to defaults (window ends) or mean "no filter".
function withoutBlanks(values: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(values).filter(([, value]) => Boolean(value)))
}
