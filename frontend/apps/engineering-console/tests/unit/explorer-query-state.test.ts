import { expect, it } from 'vitest'
import { datasetById } from '@/components/data-explorer/catalog'
import {
  backToFirstPage,
  changeChart,
  changeFilter,
  changeWindow,
  explorerChart,
  isWithinDetailLimit,
  listRequest,
  nextPage,
  parseExplorerQuery,
  toExplorerSearch,
} from '@/components/data-explorer/explorer-query-state'

const load = datasetById('hourly_load')
const forecasts = datasetById('cwa_forecasts')
const observationAudits = datasetById('cwa_observation_audits')
const national = datasetById('national_supply_demand')
const regional = datasetById('regional_supply_demand')
const units = datasetById('unit_generation')
const { chart: _chart, ...loadWithoutChart } = load
// The catalog has no chart with three units to choose from, so this copy adds one.
const nationalWithThirdUnit = {
  ...national,
  chart: { ...national.chart!, fieldOptions: [...national.chart!.fieldOptions!, { field: 'temperature_c' as const, unit: '°C' }] },
}
const LOAD_CHART = { bucket: 'auto', agg: 'avg', groupBy: undefined, fields: ['load_mw'] }
const DEFAULT_WINDOW = { start: '2026-11-22T12:00:00+08:00', end: '2026-11-23T12:00:00+08:00' }
const WITHIN_LIMIT = { start: '2026-11-20T00:00:00+08:00', end: '2026-11-21T00:00:00+08:00' }
// 40 days: beyond hourly load's 31-day list limit.
const BEYOND_LIMIT = { start: '2026-10-01T00:00:00+08:00', end: '2026-11-10T00:00:00+08:00' }

it('reads the window, declared filters, cursor and chart settings from a deep link', () => {
  const search = { ...WITHIN_LIMIT, subject: 'nationwide', cursor: 'page-2', agg: 'max' }

  expect(parseExplorerQuery(load, search, DEFAULT_WINDOW)).toEqual({
    window: WITHIN_LIMIT,
    filters: { subject: 'nationwide' },
    rows: { kind: 'page', cursor: 'page-2' },
    chart: { ...LOAD_CHART, agg: 'max' },
  })
})

it('takes a missing window from the default window and starts on the first page', () => {
  expect(parseExplorerQuery(load, {}, DEFAULT_WINDOW)).toEqual({
    window: DEFAULT_WINDOW,
    filters: {},
    rows: { kind: 'firstPage' },
    chart: LOAD_CHART,
  })
})

it('takes only the missing end from the default window', () => {
  const state = parseExplorerQuery(load, { start: '2026-11-22T00:00:00+08:00' }, DEFAULT_WINDOW)

  expect(state.window).toEqual({ start: '2026-11-22T00:00:00+08:00', end: DEFAULT_WINDOW.end })
})

it('drops the URL cursor when the window exceeds the detail limit', () => {
  const state = parseExplorerQuery(load, { ...BEYOND_LIMIT, cursor: 'page-2' }, DEFAULT_WINDOW)

  expect(state.rows).toEqual({ kind: 'overDetailLimit' })
  expect(isWithinDetailLimit(state)).toBe(false)
  expect(toExplorerSearch(load, state)).toEqual(BEYOND_LIMIT)
})

it('treats a window of exactly the detail limit as within it', () => {
  const thirtyOneDays = { start: '2026-10-01T00:00:00+08:00', end: '2026-11-01T00:00:00+08:00' }

  expect(parseExplorerQuery(load, thirtyOneDays, DEFAULT_WINDOW).rows).toEqual({ kind: 'firstPage' })
})

it.each([
  ['an unparseable window', { start: 'not-a-time', end: '2026-11-21T00:00:00+08:00' }],
  ['a start after the end', { start: '2026-11-21T00:00:00+08:00', end: '2026-11-20T00:00:00+08:00' }],
])('passes %s through on the first page for the API to reject', (_case, window) => {
  const state = parseExplorerQuery(load, window, DEFAULT_WINDOW)

  expect(state.rows).toEqual({ kind: 'firstPage' })
  expect(isWithinDetailLimit(state) && listRequest(state)).toEqual(window)
})

it('keeps declared text filters as the text the router parsed and ignores undeclared keys', () => {
  const search = { ...WITHIN_LIMIT, geocode: 63000000, dataset_id: '007', issued_at: '', typo: 'x' }

  expect(parseExplorerQuery(forecasts, search, DEFAULT_WINDOW).filters).toEqual({
    geocode: '63000000',
    dataset_id: '007',
  })
})

// The router turns `true` and `1` into a boolean and a number; other spellings arrive as text.
it.each<[unknown, boolean]>([
  [true, true],
  [1, true],
  ['yes', true],
  ['TRUE', true],
  ['Yes', true],
  [false, false],
  [0, false],
  ['', false],
  // The API reads the same spellings as true (src/shiro_mlops/service/data_explorer/values.py).
  ['on', true],
  ['T', true],
  ['y', true],
  ['off', false],
  ['no', false],
])('reads all_vintages %j as on: %s', (value, on) => {
  const state = parseExplorerQuery(forecasts, { ...WITHIN_LIMIT, all_vintages: value }, DEFAULT_WINDOW)

  expect(state.filters).toEqual(on ? { all_vintages: true } : {})
  expect(toExplorerSearch(forecasts, state)).toEqual(on ? { ...WITHIN_LIMIT, all_vintages: true } : WITHIN_LIMIT)
  expect(isWithinDetailLimit(state) && listRequest(state)).toEqual(on ? { ...WITHIN_LIMIT, all_vintages: 'true' } : WITHIN_LIMIT)
})

it('switches a filter on as true and off by removing it', () => {
  const off = parseExplorerQuery(forecasts, WITHIN_LIMIT, DEFAULT_WINDOW)

  const on = changeFilter(off, 'all_vintages', true)
  expect(on.filters).toEqual({ all_vintages: true })
  expect(toExplorerSearch(forecasts, on)).toEqual({ ...WITHIN_LIMIT, all_vintages: true })
  expect(changeFilter(on, 'all_vintages', undefined).filters).toEqual({})
})

it('removes a select or free-text filter that is cleared', () => {
  const filtered = parseExplorerQuery(forecasts, { ...WITHIN_LIMIT, geocode: '63000000' }, DEFAULT_WINDOW)

  const cleared = changeFilter(filtered, 'geocode', undefined)
  expect(cleared.filters).toEqual({})
  expect(isWithinDetailLimit(cleared) && listRequest(cleared)).toEqual(WITHIN_LIMIT)
})

it('changes the window onto the first page and keeps filters and chart settings', () => {
  const paged = parseExplorerQuery(load, { ...WITHIN_LIMIT, subject: 'north', agg: 'max', cursor: 'page-2' }, DEFAULT_WINDOW)
  const window = { start: '2026-11-19T00:00:00+08:00', end: '2026-11-19T23:59:59+08:00' }

  expect(changeWindow(load, paged, window)).toEqual({
    window,
    filters: { subject: 'north' },
    rows: { kind: 'firstPage' },
    chart: { ...LOAD_CHART, agg: 'max' },
  })
})

it('changes the window beyond the detail limit into overDetailLimit and back', () => {
  const paged = parseExplorerQuery(load, { ...WITHIN_LIMIT, cursor: 'page-2' }, DEFAULT_WINDOW)

  const widened = changeWindow(load, paged, BEYOND_LIMIT)
  expect(widened.rows).toEqual({ kind: 'overDetailLimit' })
  expect(changeWindow(load, widened, WITHIN_LIMIT).rows).toEqual({ kind: 'firstPage' })
})

it('writes the other end as resolved when only one end changes', () => {
  const state = parseExplorerQuery(load, {}, DEFAULT_WINDOW)

  expect(toExplorerSearch(load, changeWindow(load, state, { start: '2026-11-22T06:00:00+08:00' }))).toEqual({
    start: '2026-11-22T06:00:00+08:00',
    end: DEFAULT_WINDOW.end,
  })
})

it('changes a filter onto the first page', () => {
  const paged = parseExplorerQuery(load, { ...WITHIN_LIMIT, cursor: 'page-2' }, DEFAULT_WINDOW)

  expect(changeFilter(paged, 'subject', 'north')).toEqual({
    window: WITHIN_LIMIT,
    filters: { subject: 'north' },
    rows: { kind: 'firstPage' },
    chart: LOAD_CHART,
  })
})

it('keeps overDetailLimit when a filter changes', () => {
  const wide = parseExplorerQuery(load, BEYOND_LIMIT, DEFAULT_WINDOW)

  expect(changeFilter(wide, 'subject', 'north').rows).toEqual({ kind: 'overDetailLimit' })
})

it('pages forward and back to the first page', () => {
  const first = parseExplorerQuery(load, WITHIN_LIMIT, DEFAULT_WINDOW)
  if (!isWithinDetailLimit(first)) throw new Error('expected a window within the detail limit')

  const paged = nextPage(first, 'page-2')
  expect(paged.rows).toEqual({ kind: 'page', cursor: 'page-2' })
  expect(backToFirstPage(paged)).toEqual(first)
})

it('keeps the page when the chart changes and leaves a default setting out', () => {
  const paged = parseExplorerQuery(load, { ...WITHIN_LIMIT, agg: 'max', cursor: 'page-2' }, DEFAULT_WINDOW)

  const changed = changeChart(load, paged, { agg: 'avg' })
  expect(changed.rows).toEqual({ kind: 'page', cursor: 'page-2' })
  expect(changed.chart).toEqual(LOAD_CHART)
  expect(toExplorerSearch(load, changed)).toEqual({ ...WITHIN_LIMIT, cursor: 'page-2' })
})

it('keeps no agg on a count chart, from a deep link or a chart change', () => {
  const state = parseExplorerQuery(observationAudits, { ...WITHIN_LIMIT, agg: 'max' }, DEFAULT_WINDOW)

  expect(state.chart).toStrictEqual({ bucket: 'auto', groupBy: undefined, fields: ['batch_count'] })
  expect(changeChart(observationAudits, state, { agg: 'max', bucket: '1h' }).chart).toStrictEqual({
    bucket: '1h',
    groupBy: undefined,
    fields: ['batch_count'],
  })
})

it('clears agg when the raw bucket is chosen', () => {
  const state = parseExplorerQuery(load, { ...WITHIN_LIMIT, bucket: '1h', agg: 'max' }, DEFAULT_WINDOW)

  const raw = changeChart(load, state, { bucket: 'raw' })
  expect(raw.chart).toStrictEqual({ bucket: 'raw', groupBy: undefined, fields: ['load_mw'] })
  expect(toExplorerSearch(load, raw)).toEqual({ ...WITHIN_LIMIT, bucket: 'raw' })
})

it('drops the URL agg under the raw bucket', () => {
  const state = parseExplorerQuery(load, { ...WITHIN_LIMIT, bucket: 'raw', agg: 'max' }, DEFAULT_WINDOW)

  expect(state.chart).toStrictEqual({ bucket: 'raw', groupBy: undefined, fields: ['load_mw'] })
})

it('starts from the default agg when switching from raw back to an hourly bucket', () => {
  const raw = parseExplorerQuery(load, { ...WITHIN_LIMIT, bucket: 'raw', agg: 'max' }, DEFAULT_WINDOW)

  const hourly = changeChart(load, raw, { bucket: '1h' })
  expect(hourly.chart).toEqual({ ...LOAD_CHART, bucket: '1h', agg: 'avg' })
  expect(toExplorerSearch(load, hourly)).toEqual({ ...WITHIN_LIMIT, bucket: '1h' })
})

it('keeps the chosen agg under the auto bucket', () => {
  const state = parseExplorerQuery(load, { ...WITHIN_LIMIT, bucket: '1h', agg: 'max' }, DEFAULT_WINDOW)

  const auto = changeChart(load, state, { bucket: 'auto' })
  expect(auto.chart).toEqual({ ...LOAD_CHART, agg: 'max' })
  expect(explorerChart(load, auto)?.series).toEqual({
    kind: 'ready',
    params: { ...WITHIN_LIMIT, fields: ['load_mw'], agg: 'max' },
  })
})

it('resolves the default chart settings of a grouped chart', () => {
  expect(parseExplorerQuery(units, {}, DEFAULT_WINDOW).chart).toEqual({
    bucket: 'auto',
    agg: 'avg',
    groupBy: 'unit_type',
    fields: ['net_generation_mw'],
  })
})

it.each<[string, typeof load, Record<string, unknown>, Record<string, unknown>]>([
  ['an unknown bucket', load, { bucket: '5m' }, { bucket: 'auto' }],
  ['an unknown agg', load, { agg: 'median' }, { agg: 'avg' }],
  ['a group_by on a chart without grouping', load, { group_by: 'x' }, { groupBy: undefined }],
  ['a group_by outside the options', units, { group_by: 'region' }, { groupBy: 'unit_type' }],
  ['a group_by among the options', units, { group_by: 'none' }, { groupBy: 'none' }],
  ['a single field given as text', national, { fields: 'curr_util_rate_pct' }, { fields: ['curr_util_rate_pct'] }],
  ['an unknown field beside a known one', national, { fields: ['typo', 'curr_load_mw'] }, { fields: ['curr_load_mw'] }],
  ['a repeated field', national, { fields: ['curr_load_mw', 'curr_load_mw'] }, { fields: ['curr_load_mw'] }],
  ['only unknown fields', national, { fields: ['typo'] }, { fields: ['curr_load_mw', 'real_hr_maxi_sply_capacity_mw'] }],
  ['an empty field list', national, { fields: [] }, { fields: ['curr_load_mw', 'real_hr_maxi_sply_capacity_mw'] }],
  ['a field outside the default on a chart without a picker', units, { fields: ['capacity_mw'] }, { fields: ['net_generation_mw'] }],
  [
    'fields of a third unit',
    nationalWithThirdUnit,
    { fields: ['curr_util_rate_pct', 'curr_load_mw', 'temperature_c', 'fore_peak_resv_rate_pct'] },
    { fields: ['curr_util_rate_pct', 'curr_load_mw', 'fore_peak_resv_rate_pct'] },
  ],
])('resolves %s to an applicable chart setting', (_case, dataset, search, expected) => {
  const state = parseExplorerQuery(dataset, { ...WITHIN_LIMIT, ...search }, DEFAULT_WINDOW)

  expect(state.chart).toMatchObject(expected)
})

it('ignores chart settings on a dataset without a chart', () => {
  const state = parseExplorerQuery(loadWithoutChart, { ...WITHIN_LIMIT, bucket: '1h', fields: ['load_mw'] }, DEFAULT_WINDOW)

  expect(state.chart).toBeUndefined()
  expect(toExplorerSearch(loadWithoutChart, state)).toEqual(WITHIN_LIMIT)
  expect(explorerChart(loadWithoutChart, state)).toBeUndefined()
})

it('writes only the chart settings that differ from the defaults to the URL', () => {
  const defaults = parseExplorerQuery(units, WITHIN_LIMIT, DEFAULT_WINDOW)
  const changed = changeChart(units, defaults, { bucket: '1h', agg: 'max', groupBy: 'none' })
  const fields = changeChart(national, parseExplorerQuery(national, WITHIN_LIMIT, DEFAULT_WINDOW), { fields: ['curr_load_mw'] })

  expect(toExplorerSearch(units, defaults)).toEqual(WITHIN_LIMIT)
  expect(toExplorerSearch(units, changed)).toEqual({ ...WITHIN_LIMIT, bucket: '1h', agg: 'max', group_by: 'none' })
  expect(toExplorerSearch(national, fields)).toEqual({ ...WITHIN_LIMIT, fields: ['curr_load_mw'] })
})

it('requests the window, filters and fields with default chart settings left out', () => {
  const state = parseExplorerQuery(load, { ...WITHIN_LIMIT, subject: 'north', cursor: 'page-2' }, DEFAULT_WINDOW)

  expect(explorerChart(load, state)?.series).toEqual({
    kind: 'ready',
    params: { ...WITHIN_LIMIT, subject: 'north', fields: ['load_mw'] },
  })
})

it('requests chart settings that differ from the defaults', () => {
  const state = parseExplorerQuery(units, { ...WITHIN_LIMIT, bucket: '1d', agg: 'min', group_by: 'none' }, DEFAULT_WINDOW)

  expect(explorerChart(units, state)?.series).toEqual({
    kind: 'ready',
    params: { ...WITHIN_LIMIT, fields: ['net_generation_mw'], bucket: '1d', agg: 'min', group_by: 'none' },
  })
})

it('requests no agg under the raw bucket', () => {
  const state = parseExplorerQuery(units, { ...WITHIN_LIMIT, bucket: 'raw', agg: 'min', group_by: 'none' }, DEFAULT_WINDOW)

  expect(explorerChart(units, state)?.series).toEqual({
    kind: 'ready',
    params: { ...WITHIN_LIMIT, fields: ['net_generation_mw'], bucket: 'raw', group_by: 'none' },
  })
})

it('requests neither fields nor agg for a count chart', () => {
  const search = { type: 'observations', ...WITHIN_LIMIT, status: 'complete', bucket: '1h', agg: 'max', fields: ['batch_count'] }
  const state = parseExplorerQuery(observationAudits, search, DEFAULT_WINDOW)

  expect(explorerChart(observationAudits, state)?.series).toEqual({
    kind: 'ready',
    params: { ...WITHIN_LIMIT, status: 'complete', bucket: '1h' },
  })
})

it('requests only the filters the series endpoint declares', () => {
  const state = parseExplorerQuery(regional, { ...WITHIN_LIMIT, region: '北部', completeness: 'complete' }, DEFAULT_WINDOW)

  expect(explorerChart(regional, state)?.series).toEqual({
    kind: 'ready',
    params: { ...WITHIN_LIMIT, region: '北部', fields: ['load_mw'] },
  })
})

it('reports the missing required filter instead of a request', () => {
  const state = parseExplorerQuery(forecasts, { ...WITHIN_LIMIT, all_vintages: 'yes' }, DEFAULT_WINDOW)

  expect(explorerChart(forecasts, state)?.series).toEqual({ kind: 'missingFilter', filter: 'geocode', when: 'all_vintages' })
  expect(explorerChart(forecasts, changeFilter(state, 'geocode', '63000000'))?.series).toEqual({
    kind: 'ready',
    params: { ...WITHIN_LIMIT, all_vintages: 'true', geocode: '63000000', fields: ['temperature_c'] },
  })
})

it('serializes bare primitives and leaves out blanks and undeclared keys', () => {
  const search = { ...WITHIN_LIMIT, geocode: 63000000, all_vintages: true, issued_at: '', typo: 'x' }

  expect(toExplorerSearch(forecasts, parseExplorerQuery(forecasts, search, DEFAULT_WINDOW))).toEqual({
    ...WITHIN_LIMIT,
    geocode: 63000000,
    all_vintages: true,
  })
})

it('carries the fixed audit type into the URL search', () => {
  const state = parseExplorerQuery(observationAudits, { type: 'observations' }, DEFAULT_WINDOW)

  expect(toExplorerSearch(observationAudits, state)).toEqual({ type: 'observations', ...DEFAULT_WINDOW })
})

it.each([
  ['a later page with filters and chart settings', load, { ...WITHIN_LIMIT, subject: 'north', agg: 'max', cursor: 'page-2' }],
  ['a window beyond the detail limit', load, BEYOND_LIMIT],
  ['numeric, boolean and zero-padded filters', forecasts, { ...WITHIN_LIMIT, geocode: 63000000, all_vintages: true, dataset_id: '007' }],
  ['an audit type', observationAudits, { type: 'observations', ...WITHIN_LIMIT, status: 'complete' }],
  ['non-default chart settings', units, { ...WITHIN_LIMIT, bucket: '1h', agg: 'max', group_by: 'none' }],
  ['chosen fields', national, { ...WITHIN_LIMIT, fields: ['curr_util_rate_pct', 'curr_load_mw'] }],
])('round-trips %s through the URL search', (_case, dataset, search) => {
  const state = parseExplorerQuery(dataset, search, DEFAULT_WINDOW)

  expect(toExplorerSearch(dataset, state)).toEqual(search)
  expect(parseExplorerQuery(dataset, toExplorerSearch(dataset, state), DEFAULT_WINDOW)).toEqual(state)
})

it('requests the window, filters and cursor but neither chart settings nor the audit type', () => {
  const search = { type: 'observations', ...WITHIN_LIMIT, status: 'complete', bucket: '1h', cursor: 'page-2' }
  const state = parseExplorerQuery(observationAudits, search, DEFAULT_WINDOW)
  if (!isWithinDetailLimit(state)) throw new Error('expected a window within the detail limit')

  expect(listRequest(state)).toEqual({ ...WITHIN_LIMIT, status: 'complete', cursor: 'page-2' })
  expect(listRequest(backToFirstPage(state))).toEqual({ ...WITHIN_LIMIT, status: 'complete' })
})
