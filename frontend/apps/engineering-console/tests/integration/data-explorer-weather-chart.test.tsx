import { cloneElement, type ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { formatDateTime } from '@shiro-mlops/shared/i18n/format'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
import { zhTW } from '@/i18n/zh-TW'

// jsdom has no layout, so the responsive wrapper would render a zero-size chart.
vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('recharts')>()
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      cloneElement(children as ReactElement<{ width: number; height: number }>, { width: 800, height: 320 }),
  }
})

const m = zhTW
const chart = m.explorer.chart
const START = '2026-09-09T00:00:00+08:00'
const END = '2026-09-09T20:00:00+08:00'
const WINDOW = `start=${encodeURIComponent(START)}&end=${encodeURIComponent(END)}`
const EARLY_ISSUE = '2026-09-08T17:00:00+08:00'
const LATE_ISSUE = '2026-09-08T23:00:00+08:00'

const emptyList = { timezone: 'Asia/Taipei', items: [], has_more: false, next_cursor: null, missing_slots: [] }

function temperatureSeries(group: Record<string, string>, value: number) {
  return {
    field: 'temperature_c',
    unit: '°C',
    group,
    points: [
      { t: '2026-09-09T18:00:00+08:00', v: value },
      { t: '2026-09-09T19:00:00+08:00', v: value + 1 },
    ],
  }
}

function renderPath(path: string) {
  const history = createMemoryHistory({ initialEntries: [`/console${path}`] })
  const router = createAppRouter(history)
  render(<RouterProvider router={router} />)
  return router
}

function captureSeries(path: string, series: ReturnType<typeof temperatureSeries>[]) {
  const requests: URL[] = []
  server.use(
    http.get(`*${path}/series`, ({ request }) => {
      requests.push(new URL(request.url))
      return HttpResponse.json({ timezone: 'Asia/Taipei', bucket: 'raw', agg: null, series })
    }),
    http.get(`*${path}`, () => HttpResponse.json(emptyList)),
  )
  return requests
}

describe('Data Explorer weather charts', () => {
  it('draws one temperature line per station', async () => {
    const requests = captureSeries('/data/weather/observations', [
      temperatureSeries({ station_id: '466920' }, 24),
      temperatureSeries({ station_id: '467490' }, 28),
    ])
    renderPath(`/data/weather/observations?${WINDOW}`)

    await screen.findByRole('figure', {
      name: chart.figureLabel(m.explorer.datasets.cwa_observations.label, m.explorer.fields.temperature_c, '466920、467490'),
    })
    const params = requests.at(-1)!.searchParams
    expect(params.getAll('fields')).toEqual(['temperature_c'])
    expect(params.get('start')).toBe(START)
    expect(params.has('group_by')).toBe(false)
  })

  it('draws the latest version per geocode by default', async () => {
    const requests = captureSeries('/data/weather/forecasts', [
      temperatureSeries({ geocode: '63000000' }, 20),
      temperatureSeries({ geocode: '64000000' }, 26),
    ])
    renderPath(`/data/weather/forecasts?${WINDOW}`)

    await screen.findByRole('figure', {
      name: chart.figureLabel(m.explorer.datasets.cwa_forecasts.label, m.explorer.fields.temperature_c, '63000000、64000000'),
    })
    const params = requests.at(-1)!.searchParams
    expect(params.getAll('fields')).toEqual(['temperature_c'])
    expect(params.has('all_vintages')).toBe(false)
  })

  it('asks for a geocode instead of requesting series when all vintages are on without one', async () => {
    const requests = captureSeries('/data/weather/forecasts', [])
    renderPath(`/data/weather/forecasts?${WINDOW}&all_vintages=true`)

    expect(
      await screen.findByText(chart.requiresFilter(m.explorer.fields.geocode, m.explorer.fields.all_vintages)),
    ).toBeInTheDocument()
    await screen.findByText(m.explorer.results.empty)
    expect(requests).toHaveLength(0)
  })

  it('draws one line per issue time, newest first, when all vintages are on for a geocode', async () => {
    const requests = captureSeries('/data/weather/forecasts', [
      temperatureSeries({ geocode: '63000000', dataset_id: 'F-D0047-089', issued_at: EARLY_ISSUE }, 20),
      temperatureSeries({ geocode: '63000000', dataset_id: 'F-D0047-089', issued_at: LATE_ISSUE }, 22),
    ])
    renderPath(`/data/weather/forecasts?${WINDOW}&all_vintages=true&geocode=63000000`)

    const vintageNames = [LATE_ISSUE, EARLY_ISSUE].map((issuedAt) => formatDateTime(issuedAt, 'zh-TW')).join('、')
    await screen.findByRole('figure', {
      name: chart.figureLabel(m.explorer.datasets.cwa_forecasts.label, m.explorer.fields.temperature_c, vintageNames),
    })
    await waitFor(() => expect(requests.length).toBeGreaterThan(0))
    const params = requests.at(-1)!.searchParams
    expect(params.get('all_vintages')).toBe('true')
    expect(params.get('geocode')).toBe('63000000')
  })
})
