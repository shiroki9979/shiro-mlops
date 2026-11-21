import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { EMPTY_VALUE } from '@shiro-mlops/shared/i18n/format'
import { useLocaleStore, type Locale } from '@shiro-mlops/shared/i18n/locale-store'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
import { en } from '@/i18n/en'
import { zhTW } from '@/i18n/zh-TW'
// The repo-level published fixture the backend checks its export against (data contracts §6):
// 3 accumulated days, metrics null.
import emptyTrackRecord from '../../../../../tests/fixtures/published/forecast_track_record.json'

const TRACK_RECORD_URL = '/published/forecast_track_record.json'

// Data contract §6.2 sample: 10:00 Taipei is 02:00 UTC, so a formatter that falls back to the
// test host zone (TZ=UTC) would show a different hour.
const TRACK_RECORD = {
  cutoff: '2026-11-20T10:00:00+08:00',
  accumulated_days: 9,
  metrics: {
    lead_time_curve: [
      { lead_time_hours: 1, mape: 2.41, mae: 612.5 },
      { lead_time_hours: 24, mape: 4.87, mae: 1240.3 },
      { lead_time_hours: 168, mape: null, mae: null },
    ],
    lead_24: { lead_time_hours: 24, mape: 4.87, mae: 1240.3 },
    lead_24_series: [
      { target_hour: '2026-11-13T09:00:00+08:00', actual_load_mw: 25012.0, predicted_load_mw: 25830.4 },
    ],
  },
}

const DICTIONARIES = { 'zh-TW': zhTW, en } as const
type HistoryText = (typeof DICTIONARIES)[Locale]['history']

function serveTrackRecord(body: unknown) {
  server.use(http.get(TRACK_RECORD_URL, () => HttpResponse.json(body)))
}

// Only Date is faked: fake timers would stall TanStack Query and MSW.
function setNow(isoTime: string) {
  vi.setSystemTime(new Date(isoTime))
}

function renderHistory(locale: Locale = 'zh-TW') {
  useLocaleStore.setState({ preference: locale })
  const router = createAppRouter(createMemoryHistory({ initialEntries: ['/history'] }))
  render(<RouterProvider router={router} />)
  return DICTIONARIES[locale].history
}

describe('Forecast View /history track record', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    // Two hours after the 10:00 Taipei cutoff used by every sample: fresh.
    setNow('2026-11-20T04:00:00Z')
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it.each([
    ['zh-TW', '11/20 10:00'],
    ['en', '11/20, 10:00'],
  ] as const)('shows the lead-24 MAPE and MAE and the Taipei-time cutoff in %s', async (locale, cutoffText) => {
    serveTrackRecord(TRACK_RECORD)
    const text = renderHistory(locale)

    const mapeCard = await screen.findByRole('group', { name: text.metrics.lead24Mape })
    expect(within(mapeCard).getByText('4.87%')).toBeInTheDocument()
    const maeCard = screen.getByRole('group', { name: text.metrics.lead24Mae })
    expect(within(maeCard).getByText('1,240.3')).toBeInTheDocument()
    expect(within(maeCard).getByText('MW')).toBeInTheDocument()
    expect(screen.getByText(text.cutoff(cutoffText))).toBeInTheDocument()
  })

  it('reads only the published track record and calls no API', async () => {
    const requested: string[] = []
    const record = ({ request }: { request: Request }) => requested.push(new URL(request.url).pathname)
    server.events.on('request:start', record)
    serveTrackRecord(TRACK_RECORD)
    const text = renderHistory()

    await screen.findByRole('group', { name: text.metrics.lead24Mape })
    server.events.removeListener('request:start', record)

    expect(requested).toEqual([TRACK_RECORD_URL])
  })

  it.each(['zh-TW', 'en'] as const)(
    'shows no synthetic evaluation, model name or backtest wording in %s',
    async (locale) => {
      serveTrackRecord(TRACK_RECORD)
      const text = renderHistory(locale)
      await screen.findByRole('group', { name: text.metrics.lead24Mape })

      const removed = /RMSE|LightGBM|backtest|回測|尖峰|peak|結論|finding|基準|baseline/i
      expect(document.body.textContent).not.toMatch(removed)
      const dictionary = DICTIONARIES[locale]
      expect(JSON.stringify({ nav: dictionary.nav, history: dictionary.history })).not.toMatch(removed)
    },
  )

  it('shows the empty-value dash, not 0, when the lead-24 metrics are null', async () => {
    serveTrackRecord({
      ...TRACK_RECORD,
      metrics: { ...TRACK_RECORD.metrics, lead_24: { lead_time_hours: 24, mape: null, mae: null } },
    })
    const text = renderHistory()

    const mapeCard = await screen.findByRole('group', { name: text.metrics.lead24Mape })
    expect(within(mapeCard).getByText(EMPTY_VALUE)).toBeInTheDocument()
    const maeCard = screen.getByRole('group', { name: text.metrics.lead24Mae })
    expect(within(maeCard).getByText(EMPTY_VALUE)).toBeInTheDocument()
    expect(screen.queryByText(/^0(\.0+)?%?$/)).not.toBeInTheDocument()
  })

  it.each([
    ['a 500 response', () => new HttpResponse(null, { status: 500 })],
    ['a 403 response', () => new HttpResponse(null, { status: 403 })],
    ['a network error', () => HttpResponse.error()],
    ['a body that is not JSON', () => new HttpResponse('<html>not json</html>', { status: 200 })],
    ['JSON that breaks the contract', () => HttpResponse.json({ ...TRACK_RECORD, accumulated_days: 'nine' })],
  ])('shows the one neutral error state for %s', async (_case, respond) => {
    server.use(http.get(TRACK_RECORD_URL, respond))
    const text = renderHistory()

    expect(await screen.findByText(text.loadError)).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: text.metrics.lead24Mape })).not.toBeInTheDocument()
  })

  it.each([
    ['zh-TW', '11/20 10:00'],
    ['en', '11/20, 10:00'],
  ] as const)('shows the accumulated days and the cutoff, and no metrics, while accumulating in %s', async (locale, cutoffText) => {
    serveTrackRecord(emptyTrackRecord)
    const text = renderHistory(locale)

    expect(await screen.findByText(text.accumulatedDays(3))).toBeInTheDocument()
    expect(screen.getByText(text.cutoff(cutoffText))).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: text.metrics.lead24Mape })).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: text.metrics.lead24Mae })).not.toBeInTheDocument()
  })

  // Both samples are cut off at 10:00 Taipei on 11/20, which is 02:00 UTC.
  describe.each([
    ['with metrics', TRACK_RECORD, (text: HistoryText) => screen.findByRole('group', { name: text.metrics.lead24Mape })],
    ['while accumulating', emptyTrackRecord, (text: HistoryText) => screen.findByText(text.accumulatedDays(3))],
  ] as const)('the stale hint %s', (_state, trackRecord, findContent) => {
    it('shows with the content still visible once the cutoff is more than 24 hours old', async () => {
      setNow('2026-11-21T02:00:01Z')
      serveTrackRecord(trackRecord)
      const text = renderHistory()

      expect(await findContent(text)).toBeInTheDocument()
      expect(screen.getByText(text.staleHint)).toBeInTheDocument()
    })

    it('stays hidden when the cutoff is exactly 24 hours old', async () => {
      setNow('2026-11-21T02:00:00Z')
      serveTrackRecord(trackRecord)
      const text = renderHistory()

      expect(await findContent(text)).toBeInTheDocument()
      expect(screen.queryByText(text.staleHint)).not.toBeInTheDocument()
    })
  })

  it('shows no stale hint in the error state', async () => {
    setNow('2026-11-30T00:00:00Z')
    server.use(http.get(TRACK_RECORD_URL, () => new HttpResponse(null, { status: 500 })))
    const text = renderHistory()

    expect(await screen.findByText(text.loadError)).toBeInTheDocument()
    expect(screen.queryByText(text.staleHint)).not.toBeInTheDocument()
  })
})
