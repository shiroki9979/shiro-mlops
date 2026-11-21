import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { EMPTY_VALUE } from '@shiro-mlops/shared/i18n/format'
import { useLocaleStore, type Locale } from '@shiro-mlops/shared/i18n/locale-store'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
import { en } from '@/i18n/en'
import { zhTW } from '@/i18n/zh-TW'

const TRACK_RECORD_URL = '/published/forecast_track_record.json'
const DICTIONARIES = { 'zh-TW': zhTW, en } as const

// Data contract §6.2: the curve holds 168 cells, one per lead time. Every cell has a value except
// lead time 3 (no pairs) and lead time 168 (always null in normal operation).
const MISSING_LEAD_TIMES = new Set([3, 168])
const LEAD_TIME_CURVE = Array.from({ length: 168 }, (_, index) => {
  const lead = index + 1
  if (MISSING_LEAD_TIMES.has(lead)) return { lead_time_hours: lead, mape: null, mae: null }
  if (lead === 24) return { lead_time_hours: 24, mape: 4.87, mae: 1240.3 }
  return { lead_time_hours: lead, mape: 3 + lead / 100, mae: 800 + lead }
})

const TRACK_RECORD = {
  cutoff: '2026-11-20T10:00:00+08:00',
  accumulated_days: 9,
  metrics: {
    lead_time_curve: LEAD_TIME_CURVE,
    lead_24: { lead_time_hours: 24, mape: 4.87, mae: 1240.3 },
    lead_24_series: [
      { target_hour: '2026-11-13T09:00:00+08:00', actual_load_mw: 25012.0, predicted_load_mw: 25830.4 },
    ],
  },
}

// jsdom has no layout, so Recharts would draw nothing. Give every element a fixed box so the curve
// renders and responds to the pointer as it would in a browser.
const BOX = { width: 1000, height: 400 }

function stubLayout() {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    x: 0, y: 0, top: 0, left: 0, right: BOX.width, bottom: BOX.height, ...BOX, toJSON: () => ({}),
  })
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(BOX.width)
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(BOX.height)
}

function serveTrackRecord(body: unknown) {
  server.use(http.get(TRACK_RECORD_URL, () => HttpResponse.json(body)))
}

function renderHistory(locale: Locale = 'zh-TW') {
  useLocaleStore.setState({ preference: locale })
  const router = createAppRouter(createMemoryHistory({ initialEntries: ['/history'] }))
  render(<RouterProvider router={router} />)
  return DICTIONARIES[locale].history
}

async function findCurve(text: (typeof DICTIONARIES)[Locale]['history']) {
  return screen.findByRole('figure', { name: text.leadTimeCurve.title })
}

// Hover over the curve at a lead time, using the rendered x-axis tick for that lead time as the
// pointer position.
function hoverLeadTime(curve: HTMLElement, lead: number) {
  const tick = within(curve).getByText(String(lead), { selector: '.recharts-cartesian-axis-tick-value tspan' })
  const x = Number(tick.closest('text')?.getAttribute('x'))
  const surface = curve.querySelector('.recharts-wrapper') as HTMLElement
  fireEvent.mouseMove(surface, { pageX: x, pageY: BOX.height / 3, clientX: x, clientY: BOX.height / 3 })
}

describe('Forecast View /history MAPE against lead time curve', () => {
  beforeEach(stubLayout)
  afterEach(() => vi.restoreAllMocks())

  it.each(['zh-TW', 'en'] as const)('shows the curve with its title in %s when there are metrics', async (locale) => {
    serveTrackRecord(TRACK_RECORD)
    const text = renderHistory(locale)

    expect(await findCurve(text)).toBeInTheDocument()
  })

  it('shows no curve while the track record has no metrics', async () => {
    serveTrackRecord({ cutoff: TRACK_RECORD.cutoff, accumulated_days: 3, metrics: null })
    const text = renderHistory()

    await screen.findByText(text.cutoff('11/20 10:00'))
    expect(screen.queryByRole('figure', { name: text.leadTimeCurve.title })).not.toBeInTheDocument()
  })

  it('breaks the line at lead times with no MAPE instead of drawing them as 0', async () => {
    serveTrackRecord(TRACK_RECORD)
    const curve = await findCurve(renderHistory())

    // Lead times 1–2, then 4–167: two drawn runs. A null drawn as 0 would join them into one.
    const line = curve.querySelector('path.recharts-line-curve')
    const runs = line?.getAttribute('d')?.match(/M/g) ?? []
    expect(runs).toHaveLength(2)
  })

  it.each([
    ['zh-TW', '4.87%', '1,240.3 MW'],
    ['en', '4.87%', '1,240.3 MW'],
  ] as const)('shows lead time, MAPE and MAE in the tooltip in %s', async (locale, mapeText, maeText) => {
    serveTrackRecord(TRACK_RECORD)
    const text = renderHistory(locale)
    const curve = await findCurve(text)

    hoverLeadTime(curve, 24)

    const tooltip = await within(curve).findByRole('tooltip')
    expect(within(tooltip).getByText(text.leadTimeCurve.leadTime(24))).toBeInTheDocument()
    expect(within(tooltip).getByText(text.leadTimeCurve.mape)).toBeInTheDocument()
    expect(within(tooltip).getByText(mapeText)).toBeInTheDocument()
    expect(within(tooltip).getByText(text.leadTimeCurve.mae)).toBeInTheDocument()
    expect(within(tooltip).getByText(maeText)).toBeInTheDocument()
  })

  it('shows the empty-value dash in the tooltip at a lead time with no pairs', async () => {
    serveTrackRecord(TRACK_RECORD)
    const text = renderHistory()
    const curve = await findCurve(text)

    hoverLeadTime(curve, 168)

    const tooltip = await within(curve).findByRole('tooltip')
    expect(within(tooltip).getByText(text.leadTimeCurve.leadTime(168))).toBeInTheDocument()
    expect(within(tooltip).getAllByText(EMPTY_VALUE)).toHaveLength(2)
  })
})
