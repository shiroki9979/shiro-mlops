import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/server'
import { OverviewPage } from '@/routes/index'
import { useDashboardStore } from '@/store/dashboard-store'
import { useLocaleStore } from '@shiro-mlops/shared/i18n/locale-store'
import { en } from '@/i18n/en'
import { zhTW } from '@/i18n/zh-TW'

const dashboard = zhTW.dashboard
const HOUR_MS = 3_600_000

interface Step {
  target_hour: string
  predicted_load_mw: number
}

// Taipei wall-clock ISO string with the +08:00 offset the published JSON carries (data contract §6.1).
function taipeiIso(epochMs: number): string {
  return `${new Date(epochMs + 8 * HOUR_MS).toISOString().slice(0, 19)}+08:00`
}

// A published forecast whose first target hour is the top of the hour after `issuedAt`, one step per hour.
function publishedForecast(issuedAt: string, stepCount: number) {
  const firstTarget = Math.floor(Date.parse(issuedAt) / HOUR_MS) * HOUR_MS + HOUR_MS
  const steps: Step[] = Array.from({ length: stepCount }, (_, i) => ({
    target_hour: taipeiIso(firstTarget + i * HOUR_MS),
    predicted_load_mw: 30000 + i,
  }))
  return { issued_at: issuedAt, steps }
}

function servePublished(body: unknown) {
  server.use(http.get('*/published/latest_issued_forecast.json', () => HttpResponse.json(body)))
}

function freezeViewerNow(iso: string) {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(iso))
}

function renderOverview() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(
    <QueryClientProvider client={queryClient}>
      <OverviewPage />
    </QueryClientProvider>,
  )
  return { ...view, queryClient }
}

// The target hour of every row in the hourly table, in order, paging through to the last page.
// Intl separates date and time with a thin space in zh-TW; rows are compared with plain spaces.
async function allTableRows(user: ReturnType<typeof userEvent.setup>): Promise<string[]> {
  await screen.findByText(dashboard.table.targetHour)
  const rows: string[] = []
  for (;;) {
    const body = screen.getAllByRole('rowgroup')[1]
    for (const row of within(body).getAllByRole('row')) {
      rows.push((within(row).getAllByRole('cell')[0].textContent ?? '').replace(/\s+/g, ' '))
    }
    const next = screen.getByRole('button', { name: zhTW.common.nextPage })
    if (next.hasAttribute('disabled')) return rows
    await user.click(next)
  }
}

// jsdom's Blob has no text().
function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = () => reject(reader.error)
    reader.readAsText(blob)
  })
}

beforeEach(() => {
  // The preset store outlives a render; each test starts from the default 24-hour preset.
  useDashboardStore.setState(useDashboardStore.getInitialState())
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('Overview page shows the latest issued forecast', () => {
  it('shows the forecast time and the default 24-hour rows', async () => {
    servePublished(publishedForecast('2026-11-20T10:15:00+08:00', 168))
    freezeViewerNow('2026-11-20T12:30:00+08:00')

    renderOverview()

    // 10:15 Taipei is 02:15 UTC; TZ=UTC in vitest proves the label does not follow the host zone.
    expect(await screen.findByText(dashboard.issuedAt('11/20 10:15'))).toBeInTheDocument()
    expect(screen.getByText(dashboard.table.title(24))).toBeInTheDocument()
    expect(screen.getByText(dashboard.table.range(1, 10, 24))).toBeInTheDocument()
  })

  it('cuts the same rows for one forecast whenever the viewer opens it', async () => {
    const forecast = publishedForecast('2026-11-20T10:15:00+08:00', 168)
    servePublished(forecast)
    const user = userEvent.setup()

    freezeViewerNow('2026-11-20T10:20:00+08:00')
    const first = renderOverview()
    const rowsSoonAfterIssue = await allTableRows(user)
    first.unmount()

    freezeViewerNow('2026-11-21T09:45:00+08:00')
    renderOverview()
    const rowsNearlyADayLater = await allTableRows(user)

    expect(rowsSoonAfterIssue).toHaveLength(24)
    expect(rowsNearlyADayLater).toEqual(rowsSoonAfterIssue)
  })

  it('ends the 24-hour preset of a 10:15 forecast at 10:00 the next day', async () => {
    servePublished(publishedForecast('2026-11-20T10:15:00+08:00', 168))
    freezeViewerNow('2026-11-20T10:30:00+08:00')
    const user = userEvent.setup()

    renderOverview()
    const rows = await allTableRows(user)

    expect(rows[0]).toBe('11/20 11:00')
    expect(rows.at(-1)).toBe('11/21 10:00')
    expect(rows).not.toContain('11/21 11:00')
  })

  it('shows only the steps there are when the forecast covers fewer hours than the preset', async () => {
    servePublished(publishedForecast('2026-11-20T10:15:00+08:00', 20))
    freezeViewerNow('2026-11-20T10:30:00+08:00')
    const user = userEvent.setup()

    renderOverview()

    expect(await allTableRows(user)).toHaveLength(20)
    expect(screen.getByText(dashboard.table.title(20))).toBeInTheDocument()
  })

  it('shows every step the forecast covers under the week preset', async () => {
    // The load anchor lags 3 hours, so the forecast covers 168 − 3 future hours.
    servePublished(publishedForecast('2026-11-20T10:15:00+08:00', 165))
    freezeViewerNow('2026-11-20T10:30:00+08:00')
    const user = userEvent.setup()

    renderOverview()
    await user.click(await screen.findByRole('button', { name: dashboard.horizon.week }))
    const rows = await allTableRows(user)

    expect(rows).toHaveLength(165)
    expect(rows.at(-1)).toBe('11/27 07:00')
    expect(screen.getByText(dashboard.table.title(165))).toBeInTheDocument()
  })

  it('shows predicted load only: no temperature or humidity toggle, column or card', async () => {
    servePublished(publishedForecast('2026-11-20T10:15:00+08:00', 168))
    freezeViewerNow('2026-11-20T10:30:00+08:00')

    renderOverview()
    await screen.findByText(dashboard.table.targetHour)

    expect(screen.getAllByRole('columnheader').map((header) => header.textContent)).toEqual([
      dashboard.table.targetHour,
      dashboard.table.load,
    ])
    expect(screen.getAllByRole('switch')).toHaveLength(1)
    expect(screen.getByLabelText(dashboard.autoRefresh)).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/氣溫|濕度|°C/)
  })

  it('exports a CSV of target hour and predicted load only', async () => {
    servePublished(publishedForecast('2026-11-20T10:15:00+08:00', 168))
    freezeViewerNow('2026-11-20T10:30:00+08:00')
    let exported: Blob | undefined
    // jsdom implements neither object URLs nor download navigation.
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: (blob: Blob) => {
        exported = blob
        return 'blob:csv'
      },
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const user = userEvent.setup()

    renderOverview()
    await user.click(await screen.findByRole('button', { name: zhTW.common.exportCsv }))

    const lines = (await readBlob(exported!)).split('\n')
    expect(lines).toHaveLength(25)
    expect(lines[0]).toBe('Target Hour,Predicted Load (MW)')
    expect(lines[1]).toBe('2026-11-20T11:00:00+08:00,30000.00')
    expect(lines[24]).toBe('2026-11-21T10:00:00+08:00,30023.00')
  })

  it('reads the forecast time and table in English', async () => {
    servePublished(publishedForecast('2026-11-20T10:15:00+08:00', 168))
    freezeViewerNow('2026-11-20T10:30:00+08:00')
    useLocaleStore.setState({ preference: 'en' })

    renderOverview()

    expect(await screen.findByText(en.dashboard.issuedAt('11/20, 10:15'))).toBeInTheDocument()
    expect(screen.getByText(en.dashboard.table.title(24))).toBeInTheDocument()
    expect(screen.getByText(en.dashboard.chart.title)).toBeInTheDocument()
  })
})

describe('Overview page states', () => {
  it('shows an empty state and no forecast data before any forecast is issued', async () => {
    servePublished({ issued_at: null, steps: [] })
    freezeViewerNow('2026-11-20T10:30:00+08:00')

    renderOverview()

    expect(await screen.findByText(dashboard.empty)).toBeInTheDocument()
    expect(screen.queryByText(dashboard.metrics.peakTitle)).not.toBeInTheDocument()
    expect(screen.queryByText(dashboard.chart.title)).not.toBeInTheDocument()
    expect(screen.queryByText(dashboard.chart.loading)).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText(dashboard.table.loading)).not.toBeInTheDocument()
    expect(screen.queryByText(/預報時刻/)).not.toBeInTheDocument()
  })

  // An issued forecast may cover fewer than 168 hours (data contract §6.1), down to none at all, or
  // none within the selected preset. Either way the read has finished: the page must settle, not spin.
  const stepless: Array<[string, () => { issued_at: string; steps: Step[] }]> = [
    ['has no steps at all', () => ({ issued_at: '2026-11-20T10:15:00+08:00', steps: [] })],
    [
      'has no steps within the 24-hour preset',
      () => ({
        issued_at: '2026-11-20T10:15:00+08:00',
        steps: [{ target_hour: '2026-11-21T11:00:00+08:00', predicted_load_mw: 30000 }],
      }),
    ],
  ]

  it.each(stepless)('settles without loading or invented rows when the forecast %s', async (_case, body) => {
    servePublished(body())
    freezeViewerNow('2026-11-20T10:30:00+08:00')

    renderOverview()

    expect(await screen.findByText(dashboard.noStepsInHorizon)).toBeInTheDocument()
    expect(screen.getByText(dashboard.issuedAt('11/20 10:15'))).toBeInTheDocument()
    expect(screen.queryByText(dashboard.chart.loading)).not.toBeInTheDocument()
    expect(screen.queryByText(dashboard.table.loading)).not.toBeInTheDocument()
    expect(document.querySelector('.animate-pulse, .animate-spin')).toBeNull()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByText(dashboard.metrics.peakTitle)).not.toBeInTheDocument()
    expect(screen.queryByText(dashboard.unavailable)).not.toBeInTheDocument()
    expect(screen.queryByText(dashboard.empty)).not.toBeInTheDocument()
  })

  it('shows a stale notice alongside the forecast once it is more than 24 hours old', async () => {
    servePublished(publishedForecast('2026-11-20T10:15:00+08:00', 168))
    freezeViewerNow('2026-11-21T10:16:00+08:00')

    renderOverview()

    expect(await screen.findByText(dashboard.stale)).toBeInTheDocument()
    expect(screen.getByText(dashboard.issuedAt('11/20 10:15'))).toBeInTheDocument()
    expect(screen.getByText(dashboard.metrics.peakTitle)).toBeInTheDocument()
    expect(screen.getByText(dashboard.table.range(1, 10, 24))).toBeInTheDocument()
  })

  it('shows no stale notice when the forecast is exactly 24 hours old', async () => {
    servePublished(publishedForecast('2026-11-20T10:15:00+08:00', 168))
    freezeViewerNow('2026-11-21T10:15:00+08:00')

    renderOverview()

    expect(await screen.findByText(dashboard.issuedAt('11/20 10:15'))).toBeInTheDocument()
    expect(screen.queryByText(dashboard.stale)).not.toBeInTheDocument()
  })

  // Local Nginx answers a missing file with 404, CloudFront with 403 (ADR-0015 §2.4): neither means "not issued yet".
  const failedReads: Array<[string, () => Response, RegExp]> = [
    ['a 404', () => new HttpResponse('404 Not Found nginx', { status: 404 }), /404|Not Found|nginx/],
    [
      'a 403',
      () =>
        new HttpResponse('<Error><Code>AccessDenied</Code></Error>', {
          status: 403,
          headers: { 'Content-Type': 'application/xml' },
        }),
      /403|AccessDenied/,
    ],
    ['a network error', () => HttpResponse.error(), /Failed to fetch|network/i],
    [
      'a body that is not JSON',
      () => new HttpResponse('<!doctype html><title>SPA fallback</title>', { headers: { 'Content-Type': 'text/html' } }),
      /SPA fallback|JSON|Unexpected token/,
    ],
    [
      'a schema mismatch',
      () => HttpResponse.json({ issued_at: 'yesterday', steps: 'none' }),
      /yesterday|Invalid|issued_at|steps/,
    ],
  ]

  it.each(failedReads)('shows the same neutral error for %s', async (_case, respond, leaked) => {
    server.use(http.get('*/published/latest_issued_forecast.json', respond))
    freezeViewerNow('2026-11-20T10:30:00+08:00')

    renderOverview()

    expect(await screen.findByText(dashboard.unavailable)).toBeInTheDocument()
    const page = document.body.textContent ?? ''
    expect(page).not.toMatch(leaked)
    expect(page).not.toMatch(/published|make dev|API/)
    expect(screen.queryByText(dashboard.chart.loading)).not.toBeInTheDocument()
    expect(screen.queryByText(dashboard.table.loading)).not.toBeInTheDocument()
  })

  it('keeps the forecast on screen when a later refetch fails', async () => {
    let failedRefetches = 0
    // Runtime handlers are tried in order: the first read succeeds once, every later one fails.
    server.use(
      http.get(
        '*/published/latest_issued_forecast.json',
        () => HttpResponse.json(publishedForecast('2026-11-20T10:15:00+08:00', 168)),
        { once: true },
      ),
      http.get('*/published/latest_issued_forecast.json', () => {
        failedRefetches += 1
        return new HttpResponse(null, { status: 403 })
      }),
    )
    freezeViewerNow('2026-11-20T10:30:00+08:00')

    const { queryClient } = renderOverview()
    expect(await screen.findByText(dashboard.issuedAt('11/20 10:15'))).toBeInTheDocument()

    // Stands in for the auto-refresh poll firing in the background. React Query hands the failed
    // result to the page on a later macrotask, so the test waits one before looking at the screen.
    await act(async () => {
      await queryClient.refetchQueries()
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    expect(failedRefetches).toBe(1)
    expect(screen.getByText(dashboard.issuedAt('11/20 10:15'))).toBeInTheDocument()
    expect(screen.getByText(dashboard.table.range(1, 10, 24))).toBeInTheDocument()
    expect(screen.queryByText(dashboard.unavailable)).not.toBeInTheDocument()
  })

  it('reads the stale notice, empty state and error in English', async () => {
    useLocaleStore.setState({ preference: 'en' })
    freezeViewerNow('2026-11-22T10:30:00+08:00')

    servePublished(publishedForecast('2026-11-20T10:15:00+08:00', 168))
    const stale = renderOverview()
    expect(await screen.findByText(en.dashboard.stale)).toBeInTheDocument()
    stale.unmount()

    servePublished({ issued_at: null, steps: [] })
    const empty = renderOverview()
    expect(await screen.findByText(en.dashboard.empty)).toBeInTheDocument()
    empty.unmount()

    server.use(http.get('*/published/latest_issued_forecast.json', () => new HttpResponse(null, { status: 404 })))
    renderOverview()
    expect(await screen.findByText(en.dashboard.unavailable)).toBeInTheDocument()
  })
})
