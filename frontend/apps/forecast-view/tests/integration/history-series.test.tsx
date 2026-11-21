import { cloneElement, createElement, type ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { EMPTY_VALUE } from '@shiro-mlops/shared/i18n/format'
import { useLocaleStore, type Locale } from '@shiro-mlops/shared/i18n/locale-store'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
import { en } from '@/i18n/en'
import { zhTW } from '@/i18n/zh-TW'
import emptyTrackRecord from '../../../../../tests/fixtures/published/forecast_track_record.json'

// The rows each line chart on the page is handed, so a test can check what the series chart plots.
const chartData = vi.hoisted(() => [] as unknown[][])

vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('recharts')>()
  return {
    ...actual,
    // jsdom lays nothing out, so ResponsiveContainer measures zero; give the chart a fixed size instead.
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      cloneElement(children as ReactElement<{ width: number; height: number }>, { width: 800, height: 400 }),
    LineChart: (props: { data?: unknown[] }) => {
      chartData.push(props.data ?? [])
      return createElement(actual.LineChart, props)
    },
  }
})

const TRACK_RECORD_URL = '/published/forecast_track_record.json'

// The export omits 11:00 Taipei; the Forecast View does not disclose that such an hour exists (ADR-0013 §2.2).
const TRACK_RECORD = {
  cutoff: '2026-11-20T10:00:00+08:00',
  accumulated_days: 9,
  metrics: {
    lead_time_curve: [{ lead_time_hours: 24, mape: 4.87, mae: 1240.3 }],
    lead_24: { lead_time_hours: 24, mape: 4.87, mae: 1240.3 },
    lead_24_series: [
      { target_hour: '2026-11-13T09:00:00+08:00', actual_load_mw: 25012.0, predicted_load_mw: 25830.4 },
      { target_hour: '2026-11-13T10:00:00+08:00', actual_load_mw: 26100.0, predicted_load_mw: 25900.0 },
      { target_hour: '2026-11-13T12:00:00+08:00', actual_load_mw: 27000.0, predicted_load_mw: 27270.0 },
    ],
  },
}

const DICTIONARIES = { 'zh-TW': zhTW, en } as const

function serveTrackRecord(body: unknown) {
  server.use(http.get(TRACK_RECORD_URL, () => HttpResponse.json(body)))
}

function renderHistory(locale: Locale = 'zh-TW') {
  useLocaleStore.setState({ preference: locale })
  const router = createAppRouter(createMemoryHistory({ initialEntries: ['/history'] }))
  render(<RouterProvider router={router} />)
  return DICTIONARIES[locale].history
}

// Other charts on the page are handed rows too; the series chart's rows are the ones keyed by target hour.
function seriesChartData() {
  const isSeriesRow = (row: unknown) => typeof row === 'object' && row !== null && 'target_hour' in row
  const rows = [...chartData].reverse().find((data) => data.some(isSeriesRow))
  return (rows ?? []) as Array<Record<string, unknown>>
}

// The keyboard surface of the series chart, which moves its tooltip without a laid-out page.
async function findSeriesChart(text: (typeof DICTIONARIES)[Locale]['history']) {
  const figure = await screen.findByRole('figure', { name: text.series.title })
  return within(figure).getByRole('application')
}

describe('Forecast View /history lead-24 series', () => {
  it.each(['zh-TW', 'en'] as const)('shows the 30-day lead-24 series chart in %s', async (locale) => {
    serveTrackRecord(TRACK_RECORD)
    const text = renderHistory(locale)

    expect(await screen.findByRole('figure', { name: text.series.title })).toBeInTheDocument()
  })

  it('plots only the target hours the JSON contains, with no placeholder for the omitted one', async () => {
    serveTrackRecord(TRACK_RECORD)
    const text = renderHistory()
    await screen.findByText(text.series.title)

    const plotted = seriesChartData()
    expect(
      plotted.map((row) => [row.target_hour, row.actual_load_mw, row.predicted_load_mw]),
    ).toEqual([
      [Date.parse('2026-11-13T01:00:00Z'), 25012.0, 25830.4],
      [Date.parse('2026-11-13T02:00:00Z'), 26100.0, 25900.0],
      [Date.parse('2026-11-13T04:00:00Z'), 27000.0, 27270.0],
    ])
  })

  it.each([
    ['zh-TW', '11/13 09:00', '+818.4 MW (+3.27%)'],
    ['en', '11/13, 09:00', '+818.4 MW (+3.27%)'],
  ] as const)(
    'shows the Taipei target hour, actual, forecast and difference in the tooltip in %s',
    async (locale, targetHour, difference) => {
      serveTrackRecord(TRACK_RECORD)
      const text = renderHistory(locale)
      const chart = await findSeriesChart(text)

      act(() => chart.focus())

      const tooltip = await screen.findByRole('tooltip')
      expect(within(tooltip).getByText(targetHour)).toBeInTheDocument()
      expect(within(tooltip).getByText(text.series.actual)).toBeInTheDocument()
      expect(within(tooltip).getByText('25,012.0 MW')).toBeInTheDocument()
      expect(within(tooltip).getByText(text.series.predicted)).toBeInTheDocument()
      expect(within(tooltip).getByText('25,830.4 MW')).toBeInTheDocument()
      expect(within(tooltip).getByText(text.series.difference)).toBeInTheDocument()
      expect(within(tooltip).getByText(difference)).toBeInTheDocument()
    },
  )

  it('plots the points in target-hour order whatever order the JSON lists them in', async () => {
    serveTrackRecord({
      ...TRACK_RECORD,
      metrics: { ...TRACK_RECORD.metrics, lead_24_series: [...TRACK_RECORD.metrics.lead_24_series].reverse() },
    })
    const text = renderHistory()
    await screen.findByText(text.series.title)

    expect(seriesChartData().map((row) => row.target_hour)).toEqual([
      Date.parse('2026-11-13T01:00:00Z'),
      Date.parse('2026-11-13T02:00:00Z'),
      Date.parse('2026-11-13T04:00:00Z'),
    ])
  })

  it('shows the empty-value dash for the percentage difference when the actual load is 0', async () => {
    const [first, ...rest] = TRACK_RECORD.metrics.lead_24_series
    serveTrackRecord({
      ...TRACK_RECORD,
      metrics: {
        ...TRACK_RECORD.metrics,
        lead_24_series: [{ ...first, actual_load_mw: 0, predicted_load_mw: 100 }, ...rest],
      },
    })
    const text = renderHistory()
    const chart = await findSeriesChart(text)

    act(() => chart.focus())

    const tooltip = await screen.findByRole('tooltip')
    expect(within(tooltip).getByText(`+100.0 MW (${EMPTY_VALUE})`)).toBeInTheDocument()
  })

  it('moves the tooltip from one target hour in the JSON to the next, skipping the omitted hour', async () => {
    serveTrackRecord(TRACK_RECORD)
    const text = renderHistory()
    const chart = await findSeriesChart(text)

    act(() => chart.focus())
    fireEvent.keyDown(chart, { key: 'ArrowRight' })
    fireEvent.keyDown(chart, { key: 'ArrowRight' })

    const tooltip = await screen.findByRole('tooltip')
    expect(within(tooltip).getByText('11/13 12:00')).toBeInTheDocument()
    expect(within(tooltip).getByText('27,000.0 MW')).toBeInTheDocument()
    expect(within(tooltip).queryByText(EMPTY_VALUE)).not.toBeInTheDocument()
  })

  it('shows no series chart while the track record is still accumulating', async () => {
    serveTrackRecord(emptyTrackRecord)
    const text = renderHistory()

    await screen.findByText(text.cutoff('11/20 10:00'))
    expect(screen.queryByText(text.series.title)).not.toBeInTheDocument()
  })
})
