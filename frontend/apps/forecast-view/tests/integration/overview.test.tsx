import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
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
  return render(
    <QueryClientProvider client={queryClient}>
      <OverviewPage />
    </QueryClientProvider>,
  )
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
