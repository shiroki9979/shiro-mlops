import { cloneElement, type ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
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
const START = '2026-11-20T00:00:00+08:00'
const END = '2026-11-20T23:59:59+08:00'
const WINDOW = `start=${encodeURIComponent(START)}&end=${encodeURIComponent(END)}`
const STORAGE_LOAD = '儲能負載(Energy Storage System Load)'

function unitSeries(unitType: string, values: (number | null)[]) {
  return {
    field: 'net_generation_mw',
    unit: 'MW',
    group: { unit_type: unitType },
    points: values.map((v, index) => ({ t: `2026-11-20T12:${index}0:00+08:00`, v })),
  }
}

const byTypeBody = {
  timezone: 'Asia/Taipei',
  bucket: 'raw',
  agg: null,
  series: [
    unitSeries('燃氣', [9000, 9100, 9050]),
    unitSeries('太陽能', [6000, 6100, null]),
    unitSeries(STORAGE_LOAD, [-2000, -2100, -1900]),
  ],
}

const totalBody = {
  ...byTypeBody,
  series: [{ ...unitSeries('', [13000, 13100, 7150]), group: {} }],
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

function captureRequests() {
  const series: URL[] = []
  const lists: URL[] = []
  server.use(
    http.get('*/data/power/units/series', ({ request }) => {
      const url = new URL(request.url)
      series.push(url)
      return HttpResponse.json(url.searchParams.get('group_by') === 'none' ? totalBody : byTypeBody)
    }),
    http.get('*/data/power/units', ({ request }) => {
      lists.push(new URL(request.url))
      return HttpResponse.json({ timezone: 'Asia/Taipei', items: [], has_more: false, next_cursor: null, missing_slots: [] })
    }),
  )
  return { series, lists }
}

describe('Data Explorer unit generation chart', () => {
  it('requests net generation by unit type and lists each unit type in the legend', async () => {
    const requests = captureRequests()
    renderPath(`/data/power/units?${WINDOW}&unit_type=燃氣`)

    const figure = await screen.findByRole('figure', {
      name: chart.figureLabel(
        m.explorer.datasets.unit_generation.label,
        m.explorer.fields.net_generation_mw,
        ['燃氣', '太陽能', STORAGE_LOAD].join('、'),
      ),
    })
    const params = requests.series.at(-1)!.searchParams
    expect(params.getAll('fields')).toEqual(['net_generation_mw'])
    expect(params.get('unit_type')).toBe('燃氣')
    expect(params.has('group_by')).toBe(false)
    const legend = figure.querySelector('.recharts-legend-wrapper') as HTMLElement
    for (const unitType of ['燃氣', '太陽能', STORAGE_LOAD]) {
      expect(within(legend).getByText(unitType)).toBeInTheDocument()
    }
  })

  it('writes group_by to the URL and the series request but never to the list request', async () => {
    const requests = captureRequests()
    const user = userEvent.setup()
    const router = renderPath(`/data/power/units?${WINDOW}&cursor=page-2`)
    await screen.findByRole('figure')

    await choose(user, chart.groupBy, chart.groupOptions.none)

    await waitFor(() => expect(requests.series.at(-1)!.searchParams.get('group_by')).toBe('none'))
    expect(router.state.location.search).toMatchObject({ group_by: 'none', cursor: 'page-2' })
    for (const list of requests.lists) expect(list.searchParams.has('group_by')).toBe(false)
    expect(
      await screen.findByRole('figure', {
        name: chart.figureLabel(
          m.explorer.datasets.unit_generation.label,
          m.explorer.fields.net_generation_mw,
          m.explorer.fields.net_generation_mw,
        ),
      }),
    ).toBeInTheDocument()
  })

  it('leaves the default grouping out of the URL', async () => {
    captureRequests()
    const user = userEvent.setup()
    const router = renderPath(`/data/power/units?${WINDOW}&group_by=none`)
    await screen.findByRole('figure')
    expect(screen.getByRole('combobox', { name: chart.groupBy })).toHaveTextContent(chart.groupOptions.none)

    await choose(user, chart.groupBy, chart.groupOptions.unit_type)

    await waitFor(() => expect((router.state.location.search as Record<string, string>).group_by).toBeUndefined())
  })

  it('shows the grouping selector only on datasets that allow it', async () => {
    renderPath('/data/power/load')
    await screen.findByRole('figure')

    expect(screen.queryByRole('combobox', { name: chart.groupBy })).not.toBeInTheDocument()
  })
})
