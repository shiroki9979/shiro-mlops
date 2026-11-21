import { useMemo } from 'react'
import { useNavigate, useRouterState } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { datasetListQueryKey, useDatasetList } from '@/hooks/use-data-explorer'
import { defaultWindow, toRfc3339 } from '@/lib/data-explorer'
import { type ExplorerWindow, exceedsDays } from '@/lib/explorer-window'
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
  const search = useRouterState().location.search as Record<string, unknown>
  const fallbackWindow = useDefaultWindow(dataset)
  const start = searchText(search.start) || fallbackWindow.start
  const end = searchText(search.end) || fallbackWindow.end
  const filterValues = declaredFilterValues(dataset, search)
  const query: SearchValues = { start, end, ...filterValues }
  const cursor = searchText(search.cursor)
  const chartSearch = pickChartSearch(search)
  // The API would answer 422 beyond the list limit; the chart still covers the window, so the
  // table explains the limit instead of requesting rows.
  const detailLimitExceeded = exceedsDays({ start, end }, dataset.maxDays)
  const list = useDatasetList(dataset.apiPath, { ...query, cursor }, !detailLimitExceeded)

  const navigateTo = (nextSearch: Record<string, unknown>) => {
    void navigate({ to: dataset.path as never, search: toSearchParams(withoutBlanks(nextSearch)) as never })
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
    detailLimitExceeded,
    canRestart: Boolean(cursor),
    setStart: (value: string) => showFirstPageOf({ start: value }),
    setEnd: (value: string) => showFirstPageOf({ end: value }),
    // Quick ranges and shifts replace both ends in one navigation so no half-moved window is fetched.
    setWindow: (window: ExplorerWindow) => showFirstPageOf({ start: window.start, end: window.end }),
    setFilter: (key: string, value: string) => showFirstPageOf({ [key]: value }),
    goToNextPage: (nextCursor: string | undefined) => showPage(query, nextCursor),
    restartFromFirstPage,
    setChartSetting,
    refetchList: () => {
      if (!detailLimitExceeded) void list.refetch()
    },
  }
}

// Computed once per page visit so re-renders (e.g. opening a detail) do not slide an implicit window.
function useDefaultWindow(dataset: ExplorerDatasetConfig): { start: string; end: string } {
  return useMemo(() => {
    const range = defaultWindow(dataset.defaultHours, dataset.lookAheadHours ?? 0)
    return { start: toRfc3339(range.start), end: toRfc3339(range.end) }
  }, [dataset.defaultHours, dataset.lookAheadHours])
}

function declaredFilterValues(dataset: ExplorerDatasetConfig, search: Record<string, unknown>): SearchValues {
  return Object.fromEntries(dataset.filters.map((field) => [field.key, searchText(search[field.key])]))
}

// The router parses each search value as JSON, so `all_vintages=true` or `geocode=63000000`
// arrive as a boolean or a number; the API and the controls work with the text.
function searchText(value: unknown): string | undefined {
  return value === undefined || value === null ? undefined : String(value)
}

// The router also quotes strings that would parse as JSON (`"true"`); handing it the primitive
// keeps such values bare in the URL. Text that does not round-trip exactly (e.g. `007`) stays a string.
function toSearchParams(values: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(values).map(([key, value]) => [key, toSearchParam(value)]))
}

function toSearchParam(value: unknown): unknown {
  if (typeof value !== 'string') return value
  try {
    const parsed: unknown = JSON.parse(value)
    const isBarePrimitive = typeof parsed === 'boolean' || typeof parsed === 'number'
    return isBarePrimitive && String(parsed) === value ? parsed : value
  } catch {
    return value
  }
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
