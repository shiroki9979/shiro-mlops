import { type ExplorerWindow, exceedsDays } from '@/lib/explorer-window'
import { AggSchema, BucketSchema } from '@/schemas/data-explorer'
import type { ExplorerDatasetConfig, ExplorerFieldKey } from './catalog'

// Chart settings live in the URL beside the window but never reach the list request or its cursor.
export const CHART_SEARCH_KEYS = ['fields', 'group_by', 'bucket', 'agg'] as const
export type ChartSearchKey = (typeof CHART_SEARCH_KEYS)[number]
export type ChartSearch = Partial<Record<ChartSearchKey, string | string[]>>
export const DEFAULT_BUCKET = BucketSchema.options[0]
export const DEFAULT_AGG = AggSchema.options[0]
export const CHART_DEFAULTS: Partial<Record<ChartSearchKey, string>> = { bucket: DEFAULT_BUCKET, agg: DEFAULT_AGG }

// A v2 cursor is bound to the window and filters it was issued for, so only paging creates a
// `page`; every other transition lands on `firstPage`. Beyond the list limit the API would answer
// 422 while the chart still covers the window, so `overDetailLimit` requests no rows and has no
// cursor to page from.
export type FirstPageRows = { kind: 'firstPage' }
export type PageRows = { kind: 'page'; cursor: string }
export type ExplorerRows = { kind: 'overDetailLimit' } | FirstPageRows | PageRows
type FirstRows = Exclude<ExplorerRows, PageRows>
type ListableRows = FirstPageRows | PageRows

export type ExplorerFilterValues = Partial<Record<ExplorerFieldKey, string>>

export interface ExplorerQueryState<Rows extends ExplorerRows = ExplorerRows> {
  window: ExplorerWindow
  filters: ExplorerFilterValues
  rows: Rows
  chart: ChartSearch
}

export type ListableQueryState = ExplorerQueryState<ListableRows>

// `search` is what the router parsed, so `all_vintages=true` or `geocode=63000000` arrive as a
// boolean or a number. The window and filters stay text the API judges; a missing end falls back
// to `defaultWindow`, which the caller computes once per page visit.
export function parseExplorerQuery(
  dataset: ExplorerDatasetConfig,
  search: Record<string, unknown>,
  defaultWindow: ExplorerWindow,
): ExplorerQueryState {
  const window = {
    start: searchText(search.start) || defaultWindow.start,
    end: searchText(search.end) || defaultWindow.end,
  }
  const cursor = searchText(search.cursor)
  const rows = firstRows(dataset, window)
  return {
    window,
    filters: declaredFilterValues(dataset, search),
    rows: rows.kind === 'firstPage' && cursor ? { kind: 'page', cursor } : rows,
    chart: pickChartSearch(search),
  }
}

export function isWithinDetailLimit(state: ExplorerQueryState): state is ListableQueryState {
  return state.rows.kind !== 'overDetailLimit'
}

// A one-end patch keeps the other end's resolved value, so the URL then holds both.
export function changeWindow(
  dataset: ExplorerDatasetConfig,
  state: ExplorerQueryState,
  patch: Partial<ExplorerWindow>,
): ExplorerQueryState<FirstRows> {
  const window = { ...state.window, ...patch }
  return { ...state, window, rows: firstRows(dataset, window) }
}

export function changeFilter(state: ExplorerQueryState, key: ExplorerFieldKey, value: string): ExplorerQueryState<FirstRows> {
  const rows: FirstRows = state.rows.kind === 'overDetailLimit' ? state.rows : { kind: 'firstPage' }
  return { ...state, filters: { ...state.filters, [key]: value }, rows }
}

export function nextPage(state: ListableQueryState, cursor: string): ExplorerQueryState<PageRows> {
  return { ...state, rows: { kind: 'page', cursor } }
}

export function backToFirstPage(state: ListableQueryState): ExplorerQueryState<FirstPageRows> {
  return { ...state, rows: { kind: 'firstPage' } }
}

// A chart setting changes neither the rows nor what the cursor is bound to, so the page stays.
// `undefined` restores the default; the caller decides what the default is for array settings.
export function changeChartSetting<Rows extends ExplorerRows>(
  state: ExplorerQueryState<Rows>,
  key: ChartSearchKey,
  value: string | string[] | undefined,
): ExplorerQueryState<Rows> {
  const stored = CHART_DEFAULTS[key] === value ? undefined : value
  return { ...state, chart: { ...state.chart, [key]: stored } }
}

// The search object to navigate to: fixed dataset params (the audit type) travel as they are and
// undeclared keys are left behind.
export function toExplorerSearch(dataset: ExplorerDatasetConfig, state: ExplorerQueryState): Record<string, unknown> {
  return toSearchParams(withoutBlanks({
    ...dataset.search,
    ...state.window,
    ...state.filters,
    ...state.chart,
    cursor: state.rows.kind === 'page' ? state.rows.cursor : undefined,
  }))
}

export function listRequest(state: ListableQueryState): Record<string, string | undefined> {
  return {
    ...state.window,
    ...state.filters,
    ...(state.rows.kind === 'page' ? { cursor: state.rows.cursor } : {}),
  }
}

function firstRows(dataset: ExplorerDatasetConfig, window: ExplorerWindow): FirstRows {
  return exceedsDays(window, dataset.maxDays) ? { kind: 'overDetailLimit' } : { kind: 'firstPage' }
}

function declaredFilterValues(dataset: ExplorerDatasetConfig, search: Record<string, unknown>): ExplorerFilterValues {
  return Object.fromEntries(
    dataset.filters.flatMap((field) => {
      const value = searchText(search[field.key])
      return value === undefined ? [] : [[field.key, value]]
    }),
  )
}

function searchText(value: unknown): string | undefined {
  return value === undefined || value === null ? undefined : String(value)
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

// The router quotes strings that would parse as JSON (`"true"`); handing it the primitive keeps
// such values bare in the URL. Text that does not round-trip exactly (e.g. `007`) stays a string.
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
