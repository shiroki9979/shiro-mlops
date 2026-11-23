import { expect, it } from 'vitest'
import { datasetById } from '@/components/data-explorer/catalog'
import {
  backToFirstPage,
  changeChartSetting,
  changeFilter,
  changeWindow,
  isWithinDetailLimit,
  listRequest,
  nextPage,
  parseExplorerQuery,
  toExplorerSearch,
} from '@/components/data-explorer/explorer-query-state'

const load = datasetById('hourly_load')
const forecasts = datasetById('cwa_forecasts')
const observationAudits = datasetById('cwa_observation_audits')
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
    chart: { agg: 'max' },
  })
})

it('takes a missing window from the default window and starts on the first page', () => {
  expect(parseExplorerQuery(load, {}, DEFAULT_WINDOW)).toEqual({
    window: DEFAULT_WINDOW,
    filters: {},
    rows: { kind: 'firstPage' },
    chart: {},
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

it('keeps declared filter values as the text the router parsed and ignores undeclared keys', () => {
  const search = { ...WITHIN_LIMIT, geocode: 63000000, all_vintages: true, dataset_id: '007', typo: 'x' }

  expect(parseExplorerQuery(forecasts, search, DEFAULT_WINDOW).filters).toEqual({
    geocode: '63000000',
    all_vintages: 'true',
    dataset_id: '007',
  })
})

it('changes the window onto the first page and keeps filters and chart settings', () => {
  const paged = parseExplorerQuery(load, { ...WITHIN_LIMIT, subject: 'north', agg: 'max', cursor: 'page-2' }, DEFAULT_WINDOW)
  const window = { start: '2026-11-19T00:00:00+08:00', end: '2026-11-19T23:59:59+08:00' }

  expect(changeWindow(load, paged, window)).toEqual({
    window,
    filters: { subject: 'north' },
    rows: { kind: 'firstPage' },
    chart: { agg: 'max' },
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
    chart: {},
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

it('keeps the page when a chart setting changes and leaves a default setting out', () => {
  const paged = parseExplorerQuery(load, { ...WITHIN_LIMIT, agg: 'max', cursor: 'page-2' }, DEFAULT_WINDOW)

  const changed = changeChartSetting(paged, 'agg', 'avg')
  expect(changed.rows).toEqual({ kind: 'page', cursor: 'page-2' })
  expect(toExplorerSearch(load, changed)).toEqual({ ...WITHIN_LIMIT, cursor: 'page-2' })
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
