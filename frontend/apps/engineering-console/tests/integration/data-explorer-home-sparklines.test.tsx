import { cloneElement, type ReactElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
import { zhTW } from '@/i18n/zh-TW'

// jsdom has no layout, so the responsive wrapper would render a zero-size chart.
vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('recharts')>()
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      cloneElement(children as ReactElement<{ width: number; height: number }>, { width: 800, height: 48 }),
  }
})

const m = zhTW
const sparkline = m.explorer.sparkline
// 2026-09-09 20:00 in Taipei.
const NOW = new Date('2026-09-09T12:00:00Z')
const DAY_BEFORE = '2026-09-08T20:00:00+08:00'
const NOW_TAIPEI = '2026-09-09T20:00:00+08:00'
const DAY_AFTER = '2026-09-10T20:00:00+08:00'

const DATASETS = [
  ['hourly_load', '/data/power/load'],
  ['national_supply_demand', '/data/power/supply-demand'],
  ['regional_supply_demand', '/data/power/regional'],
  ['unit_generation', '/data/power/units'],
  ['cwa_observations', '/data/weather/observations'],
  ['cwa_forecasts', '/data/weather/forecasts'],
  ['cwa_observation_audits', '/data/audits?type=observations'],
  ['cwa_forecast_audits', '/data/audits?type=forecasts'],
] as const

const allStatuses = {
  timezone: 'Asia/Taipei',
  datasets: DATASETS.map(([id, href]) => ({
    id,
    label: m.explorer.datasets[id].label,
    availability: 'available',
    freshness: 'fresh',
    completeness: 'complete',
    overall: 'healthy',
    latest_source_at: '2026-09-09T20:00:00+08:00',
    latest_ingested_at: '2026-09-09T20:01:00+08:00',
    missing_identifiers: [],
    missing_slot_count: 0,
    href,
  })),
}

const emptySeries = { timezone: 'Asia/Taipei', bucket: 'raw', agg: null, series: [] }

function renderHome() {
  const history = createMemoryHistory({ initialEntries: ['/console/data'] })
  render(<RouterProvider router={createAppRouter(history)} />)
}

function captureSeriesRequests(bodies: Record<string, unknown> = {}) {
  const requests: URL[] = []
  server.use(
    http.get('*/data/status', () => HttpResponse.json(allStatuses)),
    http.get('*/series', ({ request }) => {
      const url = new URL(request.url)
      requests.push(url)
      return HttpResponse.json(bodies[url.pathname.replace(/^\/api/, '')] ?? emptySeries)
    }),
  )
  return requests
}

function paramsByPath(requests: URL[]): Record<string, [string, string][]> {
  return Object.fromEntries(
    requests.map((url) => [url.pathname.replace(/^\/api/, ''), [...url.searchParams.entries()].sort()]),
  )
}

afterEach(() => {
  vi.useRealTimers()
})

describe('Data Explorer home sparklines', () => {
  it('requests one 24-hour series per status card with the sparkline parameters', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
    const requests = captureSeriesRequests()

    renderHome()

    await waitFor(() => expect(requests).toHaveLength(8))
    expect(paramsByPath(requests)).toEqual({
      '/data/power/load/series': [['end', NOW_TAIPEI], ['fields', 'load_mw'], ['start', DAY_BEFORE]],
      '/data/power/supply-demand/series': [['end', NOW_TAIPEI], ['fields', 'curr_load_mw'], ['start', DAY_BEFORE]],
      '/data/power/regional/series': [['end', NOW_TAIPEI], ['fields', 'load_mw'], ['start', DAY_BEFORE]],
      '/data/power/units/series': [
        ['end', NOW_TAIPEI],
        ['fields', 'net_generation_mw'],
        ['group_by', 'none'],
        ['start', DAY_BEFORE],
      ],
      '/data/weather/observations/series': [['end', NOW_TAIPEI], ['fields', 'temperature_c'], ['start', DAY_BEFORE]],
      '/data/weather/forecasts/series': [['end', DAY_AFTER], ['fields', 'temperature_c'], ['start', NOW_TAIPEI]],
      '/data/audits/cwa-observations/series': [['bucket', '1h'], ['end', NOW_TAIPEI], ['start', DAY_BEFORE]],
      '/data/audits/cwa-forecasts/series': [['bucket', '1h'], ['end', NOW_TAIPEI], ['start', DAY_BEFORE]],
    })
    await screen.findAllByText(sparkline.empty)
    expect(requests).toHaveLength(8)
  })

  it('breaks a sparkline where the series has a gap', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
    captureSeriesRequests({
      '/data/power/load/series': {
        ...emptySeries,
        series: [
          {
            field: 'load_mw',
            unit: 'MW',
            group: { subject: 'nationwide' },
            points: [
              { t: '2026-09-09T16:00:00+08:00', v: 30000 },
              { t: '2026-09-09T17:00:00+08:00', v: 30500 },
              { t: '2026-09-09T18:00:00+08:00', v: null },
              { t: '2026-09-09T19:00:00+08:00', v: 31000 },
              { t: '2026-09-09T20:00:00+08:00', v: 32100 },
            ],
          },
        ],
      },
    })

    renderHome()

    const preview = await screen.findByRole('img', {
      name: sparkline.lineLabel(
        m.explorer.datasets.hourly_load.label,
        m.explorer.filters.quickRanges.last24Hours,
        m.explorer.fields.load_mw,
        'nationwide',
      ),
    })
    const path = preview.querySelector('.recharts-line-curve')!.getAttribute('d')!
    expect(path.match(/M/g)).toHaveLength(2)
  })

  it('shows hours with an incomplete audit, a complete audit, or no audit on the status grid', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
    captureSeriesRequests({
      '/data/audits/cwa-observations/series': {
        ...emptySeries,
        bucket: '1h',
        series: [
          {
            field: 'batch_count',
            unit: 'count',
            group: { status: 'complete' },
            points: Array.from({ length: 22 }, (_, index) => ({
              t: new Date(Date.parse('2026-09-08T21:00:00+08:00') + index * 3600_000).toISOString(),
              v: 1,
            })),
          },
          {
            field: 'batch_count',
            unit: 'count',
            group: { status: 'incomplete' },
            points: [{ t: '2026-09-09T18:00:00+08:00', v: 1 }],
          },
        ],
      },
    })

    renderHome()

    // 21:00 to 18:00 the next day hold complete batches, 18:00 also an incomplete one, and 19:00 and 20:00 none.
    const grid = await screen.findByRole('img', {
      name: sparkline.statusGridLabel(
        m.explorer.datasets.cwa_observation_audits.label,
        m.explorer.filters.quickRanges.last24Hours,
        [
          sparkline.statusHours(m.status.completeness.complete, '21'),
          sparkline.statusHours(m.status.completeness.incomplete, '1'),
          sparkline.statusHours(sparkline.noRecord, '2'),
        ].join('、'),
      ),
    })
    expect(grid.children).toHaveLength(24)
    // Intl may separate date and time with a narrow no-break space.
    expect(grid.children[21].getAttribute('title')!.replace(/\s/g, ' ')).toBe(
      sparkline.cellTitle('09/09 18:00', m.status.completeness.incomplete),
    )
  })
})
