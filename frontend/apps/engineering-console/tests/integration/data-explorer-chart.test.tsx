import { cloneElement, type ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
const END = '2026-09-09T20:00:00+08:00'
const WINDOW = `start=${encodeURIComponent(START)}&end=${encodeURIComponent(END)}`

const seriesBody = {
  timezone: 'Asia/Taipei',
  bucket: 'raw',
  agg: null,
  series: [
    {
      field: 'load_mw',
      unit: 'MW',
      group: { subject: 'nationwide' },
      points: [
        { t: '2026-09-09T18:00:00+08:00', v: 30100 },
        { t: '2026-09-09T19:00:00+08:00', v: null },
        { t: '2026-09-09T20:00:00+08:00', v: 32100.5 },
      ],
    },
  ],
}

// Chart settings use the shared Radix select: open the labelled combobox, then pick the option text.
async function choose(user: ReturnType<typeof userEvent.setup>, label: string, option: string) {
  await user.click(screen.getByRole('combobox', { name: label }))
  await user.click(await screen.findByRole('option', { name: option }))
}

function renderPath(path: string) {
  const history = createMemoryHistory({ initialEntries: [`/console${path}`] })
  const router = createAppRouter(history)
  render(<RouterProvider router={router} />)
  return router
}

// Points carry dots at this density, and a dot's centre is where the chart draws that bucket.
function bucketX(figure: HTMLElement, index: number): number {
  const dots = figure.querySelectorAll('.recharts-line-dots circle')
  return Number(dots[index].getAttribute('cx'))
}

function dragAcross(figure: HTMLElement, fromX: number, toX: number) {
  const surface = figure.querySelector('.recharts-wrapper') as HTMLElement
  const at = (x: number) => ({ clientX: x, clientY: 150, pageX: x, pageY: 150 })
  fireEvent.mouseDown(surface, at(fromX))
  fireEvent.mouseMove(surface, at(toX))
  fireEvent.mouseUp(surface, at(toX))
}

function captureRequests() {
  const series: URL[] = []
  const lists: URL[] = []
  server.use(
    http.get('*/data/power/load/series', ({ request }) => {
      series.push(new URL(request.url))
      return HttpResponse.json(seriesBody)
    }),
    http.get('*/data/power/load', ({ request }) => {
      lists.push(new URL(request.url))
      return HttpResponse.json({
        timezone: 'Asia/Taipei',
        items: [],
        has_more: false,
        next_cursor: null,
        missing_slots: [],
      })
    }),
  )
  return { series, lists }
}

describe('Data Explorer chart card', () => {
  it('requests the hourly load series for the shared window and filters', async () => {
    const requests = captureRequests()
    renderPath(`/data/power/load?${WINDOW}&subject=nationwide`)

    await waitFor(() => expect(requests.series.length).toBeGreaterThan(0))
    const params = requests.series.at(-1)!.searchParams
    expect(params.get('start')).toBe(START)
    expect(params.get('end')).toBe(END)
    expect(params.get('subject')).toBe('nationwide')
    expect(params.getAll('fields')).toEqual(['load_mw'])
    expect(params.has('bucket')).toBe(false)
    expect(params.has('agg')).toBe(false)
  })

  // Hourly load has no grouping selector, so a hand-written `group_by` is not applicable.
  it('draws the chart without sending an inapplicable group_by from the URL', async () => {
    const requests = captureRequests()
    renderPath(`/data/power/load?${WINDOW}&group_by=x`)

    await screen.findByRole('figure', {
      name: chart.figureLabel(m.explorer.datasets.hourly_load.label, m.explorer.fields.load_mw, 'nationwide'),
    })
    expect(screen.queryByText(chart.invalidQuery)).not.toBeInTheDocument()
    expect(requests.series.length).toBeGreaterThan(0)
    for (const series of requests.series) expect(series.searchParams.has('group_by')).toBe(false)
  })

  it('describes the chart by dataset, field, and series name', async () => {
    captureRequests()
    renderPath(`/data/power/load?${WINDOW}`)

    const figure = await screen.findByRole('figure', {
      name: chart.figureLabel(
        m.explorer.datasets.hourly_load.label,
        m.explorer.fields.load_mw,
        'nationwide',
      ),
    })
    expect(within(figure).getByText(chart.title)).toBeInTheDocument()
    expect(within(figure).getByText(chart.gapLegend)).toBeInTheDocument()
  })

  it('writes bucket and agg to the URL, keeps the cursor, and leaves them out of list requests', async () => {
    const requests = captureRequests()
    const user = userEvent.setup()
    const router = renderPath(`/data/power/load?${WINDOW}&cursor=page-2`)
    await screen.findByRole('figure')

    await choose(user, chart.bucket, chart.buckets['1d'])
    await choose(user, chart.agg, chart.aggs.max)

    await waitFor(() => expect(requests.series.at(-1)!.searchParams.get('agg')).toBe('max'))
    expect(requests.series.at(-1)!.searchParams.get('bucket')).toBe('1d')
    const search = router.state.location.search as Record<string, string>
    expect(search).toMatchObject({ bucket: '1d', agg: 'max', cursor: 'page-2' })
    for (const list of requests.lists) {
      expect(list.searchParams.has('bucket')).toBe(false)
      expect(list.searchParams.has('agg')).toBe(false)
    }
    expect(requests.lists.at(-1)!.searchParams.get('cursor')).toBe('page-2')
  })

  it('omits default chart settings from the URL and disables agg for raw', async () => {
    captureRequests()
    const user = userEvent.setup()
    const router = renderPath(`/data/power/load?${WINDOW}&bucket=1h&agg=min`)
    await screen.findByRole('figure')

    await choose(user, chart.bucket, chart.buckets.auto)
    await choose(user, chart.agg, chart.aggs.avg)

    await waitFor(() => {
      const search = router.state.location.search as Record<string, string>
      expect(search.bucket).toBeUndefined()
      expect(search.agg).toBeUndefined()
    })
    await choose(user, chart.bucket, chart.buckets.raw)
    expect(screen.getByRole('combobox', { name: chart.agg })).toBeDisabled()
  })

  it('keeps chart settings when the window changes and the cursor is cleared', async () => {
    captureRequests()
    const user = userEvent.setup()
    const router = renderPath(`/data/power/load?${WINDOW}&bucket=1d&cursor=page-2`)
    await screen.findByRole('figure')

    await user.type(screen.getByPlaceholderText('nationwide'), 'n')

    await waitFor(() => {
      const search = router.state.location.search as Record<string, string>
      expect(search.subject).toBe('n')
    })
    const search = router.state.location.search as Record<string, string>
    expect(search.bucket).toBe('1d')
    expect(search.cursor).toBeUndefined()
  })

  it('refreshes the series together with status and table', async () => {
    const requests = captureRequests()
    const user = userEvent.setup()
    renderPath(`/data/power/load?${WINDOW}`)
    await screen.findByRole('figure')
    const before = requests.series.length

    await user.click(within(screen.getByRole('main')).getByRole('button', { name: m.common.refresh }))

    await waitFor(() => expect(requests.series.length).toBe(before + 1))
  })

  it('skips the list beyond its detail limit, hints at brushing, and still draws the chart', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-21T04:30:15Z'))
    try {
      const requests = captureRequests()
      const user = userEvent.setup()
      renderPath(`/data/power/load?${WINDOW}`)
      await screen.findByText(m.explorer.results.empty)
      const listsBefore = requests.lists.length

      await user.click(screen.getByRole('button', { name: m.explorer.filters.quickRanges.last92Days }))

      expect(await screen.findByText(m.explorer.results.detailLimitExceeded('31'))).toBeInTheDocument()
      await waitFor(() => expect(requests.series.at(-1)!.searchParams.get('start')).toBe('2026-08-21T12:30:15+08:00'))
      expect(await screen.findByRole('figure')).toBeInTheDocument()
      expect(requests.lists.length).toBe(listsBefore)
      expect(screen.getByRole('button', { name: m.common.exportCsv })).toBeDisabled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('turns a brush across buckets into the window, clearing the cursor and keeping chart settings', async () => {
    const requests = captureRequests()
    const router = renderPath(`/data/power/load?${WINDOW}&agg=max&cursor=page-2`)
    const figure = await screen.findByRole('figure')
    await waitFor(() => expect(figure.querySelectorAll('.recharts-line-dots circle').length).toBe(2))

    dragAcross(figure, bucketX(figure, 0), bucketX(figure, 1))

    await waitFor(() => {
      const search = router.state.location.search as Record<string, string>
      expect(search.start).toBe('2026-09-09T18:00:00+08:00')
    })
    expect(router.state.location.search).toEqual({
      start: '2026-09-09T18:00:00+08:00',
      end: '2026-09-09T20:59:59+08:00',
      agg: 'max',
    })
    await waitFor(() => expect(requests.lists.at(-1)!.searchParams.get('end')).toBe('2026-09-09T20:59:59+08:00'))
    expect(requests.lists.at(-1)!.searchParams.has('cursor')).toBe(false)
  })

  it('keeps the window when the chart is clicked without dragging', async () => {
    captureRequests()
    const router = renderPath(`/data/power/load?${WINDOW}`)
    const figure = await screen.findByRole('figure')
    await waitFor(() => expect(figure.querySelectorAll('.recharts-line-dots circle').length).toBe(2))

    dragAcross(figure, bucketX(figure, 0), bucketX(figure, 0))

    expect(router.state.location.search).toEqual({ start: START, end: END })
  })

  it('suggests the coarser bucket the API names when the chosen one has too many points', async () => {
    server.use(
      http.get('*/data/power/load/series', () =>
        HttpResponse.json(
          { detail: { message: 'too many points', suggested_bucket: '1d' } },
          { status: 422 },
        ),
      ),
    )
    renderPath(`/data/power/load?${WINDOW}&bucket=raw`)

    expect(await screen.findByText(chart.tooManyPoints(chart.buckets['1d']))).toBeInTheDocument()
  })
})
