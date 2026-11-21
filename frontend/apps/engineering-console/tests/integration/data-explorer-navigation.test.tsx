import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
import { zhTW } from '@/i18n/zh-TW'

const m = zhTW
const filtersText = m.explorer.filters
// 12:30:15 in Taipei.
const NOW = new Date('2026-11-21T04:30:15Z')

function renderPath(path: string) {
  const history = createMemoryHistory({ initialEntries: [`/console${path}`] })
  render(<RouterProvider router={createAppRouter(history)} />)
  return history
}

function urlParams(history: ReturnType<typeof createMemoryHistory>): Record<string, string> {
  return Object.fromEntries(new URLSearchParams(history.location.search))
}

function recordListRequests(apiPath: string): URL[] {
  const requests: URL[] = []
  server.use(http.get(`*${apiPath}`, ({ request }) => {
    requests.push(new URL(request.url))
    return HttpResponse.json({ timezone: 'Asia/Taipei', items: [], has_more: false, next_cursor: null, missing_slots: [] })
  }))
  return requests
}

const windowQuery = (start: string, end: string) => new URLSearchParams({ start, end }).toString()

describe('Data Explorer window navigation', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
  })
  afterEach(() => vi.useRealTimers())

  it('moves from today to the whole of yesterday and drops the cursor', async () => {
    const requests = recordListRequests('/data/power/regional')
    const user = userEvent.setup()
    const history = renderPath(
      `/data/power/regional?${windowQuery('2026-11-19T00:00:00+08:00', '2026-11-19T06:00:00+08:00')}&cursor=old`,
    )
    await screen.findByText(m.explorer.results.empty)

    await user.click(screen.getByRole('button', { name: filtersText.quickRanges.today }))
    await user.click(screen.getByRole('button', { name: filtersText.shiftEarlier }))

    await waitFor(() => expect(urlParams(history)).toEqual({
      start: '2026-11-20T00:00:00+08:00',
      end: '2026-11-20T23:59:59+08:00',
    }))
    await waitFor(() => expect(requests.at(-1)!.searchParams.get('start')).toBe('2026-11-20T00:00:00+08:00'))
    expect(requests.at(-1)!.searchParams.get('end')).toBe('2026-11-20T23:59:59+08:00')
    expect(requests.at(-1)!.searchParams.has('cursor')).toBe(false)
  })

  const quickRanges = filtersText.quickRanges
  it.each([
    ['/data/power/regional', quickRanges.today, '2026-11-21T00:00:00+08:00', '2026-11-21T23:59:59+08:00'],
    ['/data/power/regional', quickRanges.last24Hours, '2026-11-20T12:30:15+08:00', '2026-11-21T12:30:15+08:00'],
    ['/data/power/regional', quickRanges.last7Days, '2026-11-14T12:30:15+08:00', '2026-11-21T12:30:15+08:00'],
    ['/data/power/regional', quickRanges.detailLimit('7'), '2026-11-14T12:30:15+08:00', '2026-11-21T12:30:15+08:00'],
    ['/data/power/load', quickRanges.detailLimit('31'), '2026-10-21T12:30:15+08:00', '2026-11-21T12:30:15+08:00'],
    ['/data/weather/forecasts', quickRanges.next24Hours, '2026-11-21T12:30:15+08:00', '2026-11-22T12:30:15+08:00'],
    ['/data/weather/forecasts', quickRanges.next72Hours, '2026-11-21T12:30:15+08:00', '2026-11-24T12:30:15+08:00'],
    ['/data/weather/forecasts', quickRanges.next7Days, '2026-11-21T12:30:15+08:00', '2026-11-28T12:30:15+08:00'],
    ['/data/weather/forecasts', quickRanges.next14Days, '2026-11-21T12:30:15+08:00', '2026-12-05T12:30:15+08:00'],
  ])('writes the %s quick range "%s" window to the URL', async (path, label, start, end) => {
    const requests = recordListRequests(path)
    const user = userEvent.setup()
    const history = renderPath(`${path}?cursor=old`)
    await screen.findByText(m.explorer.results.empty)

    await user.click(screen.getByRole('button', { name: label }))

    await waitFor(() => expect(urlParams(history)).toEqual({ start, end }))
    await waitFor(() => expect(requests.at(-1)!.searchParams.get('start')).toBe(start))
    expect(requests.at(-1)!.searchParams.get('end')).toBe(end)
  })

  it('offers only forward quick ranges on the forecast page', async () => {
    recordListRequests('/data/weather/forecasts')
    renderPath('/data/weather/forecasts')
    await screen.findByText(m.explorer.results.empty)

    expect(screen.getByRole('button', { name: quickRanges.next72Hours })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: quickRanges.today })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: quickRanges.last24Hours })).not.toBeInTheDocument()
  })
})

describe('Data Explorer fixed-value filters', () => {
  const fields = m.explorer.fields
  const listWindow = windowQuery('2026-11-21T00:00:00+08:00', '2026-11-21T23:59:59+08:00')

  it.each([
    ['/data/power/regional', '/data/power/regional', fields.region, '中部', 'region', '中部'],
    ['/data/power/regional', '/data/power/regional', fields.completeness, m.status.completeness.incomplete, 'completeness', 'incomplete'],
    ['/data/audits?type=observations', '/data/audits/cwa-observations', fields.status, m.status.completeness.complete, 'status', 'complete'],
    ['/data/audits?type=forecasts', '/data/audits/cwa-forecasts', fields.status, m.status.completeness.incomplete, 'status', 'incomplete'],
  ])('sends the %s "%s" select choice to the URL and the list', async (path, apiPath, label, option, key, value) => {
    const requests = recordListRequests(apiPath)
    const user = userEvent.setup()
    const history = renderPath(`${path}${path.includes('?') ? '&' : '?'}${listWindow}&cursor=old`)
    await screen.findByText(m.explorer.results.empty)

    await user.click(screen.getByRole('combobox', { name: label }))
    await user.click(await screen.findByRole('option', { name: option }))

    await waitFor(() => expect(urlParams(history)[key]).toBe(value))
    expect(urlParams(history)).not.toHaveProperty('cursor')
    await waitFor(() => expect(requests.at(-1)!.searchParams.get(key)).toBe(value))
  })

  it('clears a select filter with the no-filter option', async () => {
    const requests = recordListRequests('/data/power/regional')
    const user = userEvent.setup()
    const history = renderPath(`/data/power/regional?${listWindow}&region=${encodeURIComponent('北部')}`)
    await screen.findByText(m.explorer.results.empty)
    expect(screen.getByRole('combobox', { name: fields.region })).toHaveTextContent('北部')

    await user.click(screen.getByRole('combobox', { name: fields.region }))
    await user.click(await screen.findByRole('option', { name: m.explorer.filters.noFilter }))

    await waitFor(() => expect(urlParams(history)).not.toHaveProperty('region'))
    await waitFor(() => expect(requests.at(-1)!.searchParams.has('region')).toBe(false))
    expect(screen.getByRole('combobox', { name: fields.region })).toHaveTextContent(m.explorer.filters.noFilter)
  })

  it('reads a deep-linked all_vintages=true as an enabled switch', async () => {
    const requests = recordListRequests('/data/weather/forecasts')
    renderPath(`/data/weather/forecasts?${listWindow}&all_vintages=true`)
    await screen.findByText(m.explorer.results.empty)

    expect(screen.getByRole('switch', { name: fields.all_vintages })).toBeChecked()
    expect(requests.at(-1)!.searchParams.get('all_vintages')).toBe('true')
  })

  it('toggles all vintages through the URL and the list request', async () => {
    const requests = recordListRequests('/data/weather/forecasts')
    const user = userEvent.setup()
    const history = renderPath(`/data/weather/forecasts?${listWindow}`)
    await screen.findByText(m.explorer.results.empty)

    await user.click(screen.getByRole('switch', { name: fields.all_vintages }))

    await waitFor(() => expect(urlParams(history).all_vintages).toBe('true'))
    await waitFor(() => expect(requests.at(-1)!.searchParams.get('all_vintages')).toBe('true'))
    expect(screen.getByRole('switch', { name: fields.all_vintages })).toBeChecked()

    await user.click(screen.getByRole('switch', { name: fields.all_vintages }))

    await waitFor(() => expect(urlParams(history)).not.toHaveProperty('all_vintages'))
    expect(screen.getByRole('switch', { name: fields.all_vintages })).not.toBeChecked()
  })
})
