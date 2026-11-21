import { cloneElement, type ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
      cloneElement(children as ReactElement<{ width: number; height: number }>, { width: 800, height: 320 }),
  }
})

const m = zhTW
const chart = m.explorer.chart
const START = '2026-09-09T00:00:00+08:00'
const END = '2026-09-09T23:59:59+08:00'
const WINDOW = `start=${encodeURIComponent(START)}&end=${encodeURIComponent(END)}`

function countSeries(field: string) {
  return {
    timezone: 'Asia/Taipei',
    bucket: '1h',
    agg: null,
    series: [
      {
        field,
        unit: 'count',
        group: { status: 'complete' },
        points: [
          { t: '2026-09-09T10:00:00+08:00', v: 2 },
          { t: '2026-09-09T11:00:00+08:00', v: 1 },
        ],
      },
      {
        field,
        unit: 'count',
        group: { status: 'incomplete' },
        points: [{ t: '2026-09-09T10:00:00+08:00', v: 1 }],
      },
    ],
  }
}

function captureSeries(path: string, field: string) {
  const requests: URL[] = []
  server.use(
    http.get(`*${path}`, ({ request }) => {
      requests.push(new URL(request.url))
      return HttpResponse.json(countSeries(field))
    }),
  )
  return requests
}

function renderPath(path: string) {
  const history = createMemoryHistory({ initialEntries: [`/console${path}`] })
  const router = createAppRouter(history)
  render(<RouterProvider router={router} />)
  return router
}

// The centre of a bar is where the chart draws that bucket.
function barCentres(figure: HTMLElement): number[] {
  const bars = [...figure.querySelectorAll('.recharts-bar-rectangle path')]
  const centres = bars.map((bar) => Number(bar.getAttribute('x')) + Number(bar.getAttribute('width')) / 2)
  return [...new Set(centres)].sort((a, b) => a - b)
}

function dragAcross(figure: HTMLElement, fromX: number, toX: number) {
  const surface = figure.querySelector('.recharts-wrapper') as HTMLElement
  const at = (x: number) => ({ clientX: x, clientY: 150, pageX: x, pageY: 150 })
  fireEvent.mouseDown(surface, at(fromX))
  fireEvent.mouseMove(surface, at(toX))
  fireEvent.mouseUp(surface, at(toX))
}

describe('Data Explorer audit status timeline', () => {
  it('requests observation batch counts without fields or agg and lists statuses in the legend', async () => {
    const requests = captureSeries('/data/audits/cwa-observations/series', 'batch_count')
    renderPath(`/data/audits?type=observations&${WINDOW}&status=complete`)

    const figure = await screen.findByRole('figure', {
      name: chart.figureLabel(
        m.explorer.datasets.cwa_observation_audits.label,
        m.explorer.fields.batch_count,
        `${m.status.completeness.complete}、${m.status.completeness.incomplete}`,
      ),
    })
    const params = requests.at(-1)!.searchParams
    expect(params.get('start')).toBe(START)
    expect(params.get('end')).toBe(END)
    expect(params.get('status')).toBe('complete')
    expect(params.has('fields')).toBe(false)
    expect(params.has('agg')).toBe(false)
    expect(params.has('type')).toBe(false)
    await waitFor(() => expect(within(figure).getByText(m.status.completeness.incomplete)).toBeInTheDocument())
    expect(within(figure).getByText(m.status.completeness.complete)).toBeInTheDocument()
    expect(within(figure).queryByLabelText(chart.agg)).not.toBeInTheDocument()
  })

  it('requests forecast version counts for the forecast audit page', async () => {
    const requests = captureSeries('/data/audits/cwa-forecasts/series', 'version_count')
    renderPath(`/data/audits?type=forecasts&${WINDOW}&dataset_id=F-D0047-089`)

    const figure = await screen.findByRole('figure', {
      name: chart.figureLabel(
        m.explorer.datasets.cwa_forecast_audits.label,
        m.explorer.fields.version_count,
        `${m.status.completeness.complete}、${m.status.completeness.incomplete}`,
      ),
    })
    const params = requests.at(-1)!.searchParams
    expect(params.get('dataset_id')).toBe('F-D0047-089')
    expect(params.has('fields')).toBe(false)
    await waitFor(() => expect(within(figure).getByText(m.status.completeness.complete)).toBeInTheDocument())
  })

  it('turns a brush across status bars into the window', async () => {
    captureSeries('/data/audits/cwa-observations/series', 'batch_count')
    const router = renderPath(`/data/audits?type=observations&${WINDOW}`)
    const figure = await screen.findByRole('figure')
    await waitFor(() => expect(barCentres(figure)).toHaveLength(2))

    const [first, second] = barCentres(figure)
    dragAcross(figure, first, second)

    await waitFor(() =>
      expect(router.state.location.search).toMatchObject({
        type: 'observations',
        start: '2026-09-09T10:00:00+08:00',
        end: '2026-09-09T11:59:59+08:00',
      }),
    )
  })
})
