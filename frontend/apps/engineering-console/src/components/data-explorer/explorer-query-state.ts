import type { QueryParams } from '@/lib/api-client'
import { type ExplorerWindow, exceedsDays } from '@/lib/explorer-window'
import { type Agg, AggSchema, type Bucket, BucketSchema } from '@/schemas/data-explorer'
import type { ExplorerChartConfig, ExplorerDatasetConfig, ExplorerFieldKey, ExplorerGroupOption } from './catalog'
import { MAX_CHART_UNITS } from './chart-fields'

const DEFAULT_BUCKET = BucketSchema.options[0]
export const DEFAULT_AGG = AggSchema.options[0]

// Chart settings live in the URL beside the window but never reach the list request or its cursor.
// They hold resolved values: a URL value that is invalid or does not apply to the chart reads as
// the default, and a setting equal to its default stays out of the URL. A count chart never
// sends `agg` and a chart without `groupOptions` never sends `group_by`. An explicit `raw` bucket
// has no agg, so a shared link never carries one that does not apply; `auto` keeps it because the
// server may resolve `auto` to an aggregating bucket.
export type ChartSettings = Omit<ChartChoices, 'bucket' | 'agg'> &
  ({ bucket: 'raw'; agg?: never } | { bucket: Exclude<Bucket, 'raw'>; agg: Agg })

// What the chart card's selects can ask for; `changeChart` resolves it like a deep link.
export type ChartSettingsPatch = Partial<ChartChoices>

interface ChartChoices {
  bucket: Bucket
  agg: Agg
  groupBy: ExplorerGroupOption | undefined
  fields: ExplorerFieldKey[]
}

// A v2 cursor is bound to the window and filters it was issued for, so only paging creates a
// `page`; every other transition lands on `firstPage`. Beyond the list limit the API would answer
// 422 while the chart still covers the window, so `overDetailLimit` requests no rows and has no
// cursor to page from.
export type FirstPageRows = { kind: 'firstPage' }
export type PageRows = { kind: 'page'; cursor: string }
export type ExplorerRows = { kind: 'overDetailLimit' } | FirstPageRows | PageRows
type FirstRows = Exclude<ExplorerRows, PageRows>
type ListableRows = FirstPageRows | PageRows

// A switch is on (`true`) or absent; select and free-text values are non-empty text the API judges.
export type ExplorerFilterValue = string | true
export type ExplorerFilterValues = Partial<Record<ExplorerFieldKey, ExplorerFilterValue>>

export interface ExplorerQueryState<Rows extends ExplorerRows = ExplorerRows> {
  window: ExplorerWindow
  filters: ExplorerFilterValues
  rows: Rows
  // Undefined for a dataset without a chart.
  chart: ChartSettings | undefined
}

export type ListableQueryState = ExplorerQueryState<ListableRows>

// `search` is what the router parsed, so `all_vintages=true` or `geocode=63000000` arrive as a
// boolean or a number. The window and select or free-text filters stay text the API judges; a
// missing end falls back to `defaultWindow`, which the caller computes once per page visit.
// Switches are the one place the truth rule applies, so every spelling of "on" reaches the URL
// and the requests as `true`.
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
    chart: dataset.chart && resolveChart(dataset.chart, {
      bucket: search.bucket,
      agg: search.agg,
      groupBy: search.group_by,
      fields: search.fields,
    }),
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

// `false` or an empty value removes the filter.
export function changeFilter(
  state: ExplorerQueryState,
  key: ExplorerFieldKey,
  value: string | boolean,
): ExplorerQueryState<FirstRows> {
  const rows: FirstRows = state.rows.kind === 'overDetailLimit' ? state.rows : { kind: 'firstPage' }
  const { [key]: _previous, ...others } = state.filters
  const filters: ExplorerFilterValues = value === false || value === '' ? others : { ...others, [key]: value }
  return { ...state, filters, rows }
}

export function nextPage(state: ListableQueryState, cursor: string): ExplorerQueryState<PageRows> {
  return { ...state, rows: { kind: 'page', cursor } }
}

export function backToFirstPage(state: ListableQueryState): ExplorerQueryState<FirstPageRows> {
  return { ...state, rows: { kind: 'firstPage' } }
}

// A chart change touches neither the rows nor what the cursor is bound to, so the page stays.
export function changeChart<Rows extends ExplorerRows>(
  dataset: ExplorerDatasetConfig,
  state: ExplorerQueryState<Rows>,
  patch: ChartSettingsPatch,
): ExplorerQueryState<Rows> {
  if (!dataset.chart || !state.chart) return state
  return { ...state, chart: resolveChart(dataset.chart, { ...state.chart, ...patch }) }
}

// The search object to navigate to: fixed dataset params (the audit type) travel as they are and
// undeclared keys are left behind.
export function toExplorerSearch(dataset: ExplorerDatasetConfig, state: ExplorerQueryState): Record<string, unknown> {
  return toSearchParams(withoutBlanks({
    ...dataset.search,
    ...state.window,
    ...state.filters,
    ...(dataset.chart && state.chart ? chartSearch(dataset.chart, state.chart) : {}),
    cursor: state.rows.kind === 'page' ? state.rows.cursor : undefined,
  }))
}

export function listRequest(state: ListableQueryState): Record<string, string | undefined> {
  return {
    ...state.window,
    ...filterRequestValues(state.filters),
    ...(state.rows.kind === 'page' ? { cursor: state.rows.cursor } : {}),
  }
}

// Either the chart can be requested, or a switch that is on needs a filter the URL lacks.
export type SeriesRequest =
  | { kind: 'missingFilter'; filter: ExplorerFieldKey; when: ExplorerFieldKey }
  | { kind: 'ready'; params: QueryParams }

// The window always travels; dataset filters only those the series endpoint declares, when it
// declares any. Fields always travel so the request names what the chart draws.
export function seriesRequest(dataset: ExplorerDatasetConfig, state: ExplorerQueryState): SeriesRequest | undefined {
  const { chart } = dataset
  const settings = state.chart
  if (!chart || !settings) return undefined
  const required = chart.requiredFilter
  if (required && state.filters[required.when] === true && !state.filters[required.filter]) {
    return { kind: 'missingFilter', filter: required.filter, when: required.when }
  }
  const declared = chart.seriesFilters
  const filters = declared
    ? Object.fromEntries(Object.entries(state.filters).filter(([key]) => declared.includes(key as ExplorerFieldKey)))
    : state.filters
  const { bucket, agg, group_by: groupBy } = chartSearch(chart, settings)
  const base = { ...state.window, ...filterRequestValues(filters), ...(bucket ? { bucket } : {}) }
  if (chart.measure === 'count') return { kind: 'ready', params: base }
  return {
    kind: 'ready',
    params: { ...base, fields: settings.fields, ...(agg ? { agg } : {}), ...(groupBy ? { group_by: groupBy } : {}) },
  }
}

function firstRows(dataset: ExplorerDatasetConfig, window: ExplorerWindow): FirstRows {
  return exceedsDays(window, dataset.maxDays) ? { kind: 'overDetailLimit' } : { kind: 'firstPage' }
}

function filterRequestValues(filters: ExplorerFilterValues): Partial<Record<ExplorerFieldKey, string>> {
  return Object.fromEntries(Object.entries(filters).map(([key, value]) => [key, String(value)]))
}

function declaredFilterValues(dataset: ExplorerDatasetConfig, search: Record<string, unknown>): ExplorerFilterValues {
  return Object.fromEntries(
    dataset.filters.flatMap((field): [ExplorerFieldKey, ExplorerFilterValue][] => {
      const raw = search[field.key]
      if (field.control?.kind === 'switch') return isTruthy(raw) ? [[field.key, true]] : []
      const value = searchText(raw)
      return value ? [[field.key, value]] : []
    }),
  )
}

// SYNC(src/shiro_mlops/service/data_explorer/values.py): is_truthy.
const TRUTHY_VALUES = new Set(['1', 'true', 'yes'])

function isTruthy(value: unknown): boolean {
  return value !== undefined && value !== null && TRUTHY_VALUES.has(String(value).toLowerCase())
}

function searchText(value: unknown): string | undefined {
  return value === undefined || value === null ? undefined : String(value)
}

interface RawChartSettings {
  bucket: unknown
  agg?: unknown
  groupBy: unknown
  fields: unknown
}

function resolveChart(chart: ExplorerChartConfig, raw: RawChartSettings): ChartSettings {
  const groupOptions = chart.groupOptions
  const groupBy = groupOptions ? optionOr(raw.groupBy, groupOptions, groupOptions[0]) : undefined
  const fields = resolveFields(chart, raw.fields)
  const bucket = optionOr(raw.bucket, BucketSchema.options, DEFAULT_BUCKET)
  if (bucket === 'raw') return { bucket, groupBy, fields }
  const agg = chart.measure === 'count' ? DEFAULT_AGG : optionOr(raw.agg, AggSchema.options, DEFAULT_AGG)
  return { bucket, agg, groupBy, fields }
}

// The URL holds one field as text and several as an array. Only fields the chart offers count,
// within the same two-unit limit as the field picker, in selection order; none means the default.
function resolveFields(chart: ExplorerChartConfig, raw: unknown): ExplorerFieldKey[] {
  const options = chart.fieldOptions ?? chart.fields.map((field) => ({ field, unit: undefined }))
  const unitOf = new Map<unknown, string | undefined>(options.map((option) => [option.field, option.unit]))
  const units: (string | undefined)[] = []
  const fields: ExplorerFieldKey[] = []
  for (const value of Array.isArray(raw) ? raw : [raw]) {
    const field = value as ExplorerFieldKey
    if (!unitOf.has(field) || fields.includes(field)) continue
    const unit = unitOf.get(field)
    if (!units.includes(unit)) {
      if (units.length >= MAX_CHART_UNITS) continue
      units.push(unit)
    }
    fields.push(field)
  }
  return fields.length > 0 ? fields : [...chart.fields]
}

interface ChartSearch {
  bucket?: Bucket
  agg?: Agg
  group_by?: ExplorerGroupOption
  fields?: ExplorerFieldKey[]
}

// Settings equal to their default are left out, so two links to the same chart look the same.
function chartSearch(chart: ExplorerChartConfig, settings: ChartSettings): ChartSearch {
  const isDefaultFields =
    settings.fields.length === chart.fields.length && settings.fields.every((field, index) => field === chart.fields[index])
  return {
    bucket: settings.bucket === DEFAULT_BUCKET ? undefined : settings.bucket,
    agg: settings.agg === DEFAULT_AGG ? undefined : settings.agg,
    group_by: settings.groupBy === chart.groupOptions?.[0] ? undefined : settings.groupBy,
    fields: isDefaultFields ? undefined : settings.fields,
  }
}

function optionOr<T extends string>(value: unknown, options: readonly T[], fallback: T): T {
  return options.includes(value as T) ? (value as T) : fallback
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
