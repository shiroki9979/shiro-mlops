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
const fields = m.explorer.fields
const START = '2026-09-09T00:00:00+08:00'
const END = '2026-09-09T20:00:00+08:00'
const WINDOW = `start=${encodeURIComponent(START)}&end=${encodeURIComponent(END)}`
const NATIONAL = '/data/power/supply-demand'
const REGIONAL = '/data/power/regional'

function nationalSeries(requestedFields: string[]) {
  const units: Record<string, string> = { curr_util_rate_pct: '%', fore_peak_resv_rate_pct: '%' }
  return {
    timezone: 'Asia/Taipei',
    bucket: 'raw',
    agg: null,
    series: requestedFields.map((field) => ({
      field,
      unit: units[field] ?? 'MW',
      group: {},
      points: [
        { t: '2026-09-09T19:50:00+08:00', v: 32000 },
        { t: '2026-09-09T20:00:00+08:00', v: 32421 },
      ],
    })),
  }
}

function renderPath(path: string) {
  const history = createMemoryHistory({ initialEntries: [`/console${path}`] })
  const router = createAppRouter(history)
  render(<RouterProvider router={router} />)
  return router
}

function captureNationalSeries() {
  const requests: URL[] = []
  server.use(
    http.get('*/data/power/supply-demand/series', ({ request }) => {
      const url = new URL(request.url)
      requests.push(url)
      return HttpResponse.json(nationalSeries(url.searchParams.getAll('fields')))
    }),
  )
  return requests
}

describe('National supply-demand chart', () => {
  it('draws current load and real-time max supply capacity by default', async () => {
    const requests = captureNationalSeries()
    renderPath(`${NATIONAL}?${WINDOW}`)

    await screen.findByRole('figure', {
      name: chart.figureLabel(
        m.explorer.datasets.national_supply_demand.label,
        `${fields.curr_load_mw}、${fields.real_hr_maxi_sply_capacity_mw}`,
        `${fields.curr_load_mw}、${fields.real_hr_maxi_sply_capacity_mw}`,
      ),
    })
    expect(requests.at(-1)!.searchParams.getAll('fields')).toEqual([
      'curr_load_mw',
      'real_hr_maxi_sply_capacity_mw',
    ])
  })

  it('writes the chosen fields to the URL and the series request, keeping defaults out of the URL', async () => {
    const requests = captureNationalSeries()
    const user = userEvent.setup()
    const router = renderPath(`${NATIONAL}?${WINDOW}&cursor=page-2`)
    await screen.findByRole('figure')

    await user.click(screen.getByRole('button', { name: chart.fieldPicker }))
    await user.click(screen.getByRole('checkbox', { name: fields.curr_util_rate_pct }))

    await waitFor(() =>
      expect(requests.at(-1)!.searchParams.getAll('fields')).toEqual([
        'curr_load_mw',
        'real_hr_maxi_sply_capacity_mw',
        'curr_util_rate_pct',
      ]),
    )
    expect(router.state.location.search).toMatchObject({
      fields: ['curr_load_mw', 'real_hr_maxi_sply_capacity_mw', 'curr_util_rate_pct'],
      cursor: 'page-2',
    })

    await user.click(screen.getByRole('checkbox', { name: fields.curr_util_rate_pct }))

    await waitFor(() => expect(router.state.location.search).not.toHaveProperty('fields'))
  })

  it('keeps at least one field selected', async () => {
    captureNationalSeries()
    const user = userEvent.setup()
    renderPath(`${NATIONAL}?${WINDOW}&fields=curr_load_mw`)
    await screen.findByRole('figure')

    await user.click(screen.getByRole('button', { name: chart.fieldPicker }))

    expect(screen.getByRole('checkbox', { name: fields.curr_load_mw })).toBeDisabled()
  })

  it('shows power in both MW and 萬瓩 in the tooltip, and percentages once', async () => {
    captureNationalSeries()
    renderPath(`${NATIONAL}?${WINDOW}&fields=curr_load_mw&fields=curr_util_rate_pct`)
    const figure = await screen.findByRole('figure')
    await waitFor(() => expect(figure.querySelectorAll('.recharts-line-dots circle').length).toBe(4))

    hoverBucket(figure, 1)

    const tooltip = await waitFor(() => figure.querySelector('.recharts-tooltip-wrapper') as HTMLElement)
    expect(await within(tooltip).findByText('32,421 MW（3,242.1 萬瓩）')).toBeInTheDocument()
    expect(within(tooltip).getByText('32,421 %')).toBeInTheDocument()
  })
})

function hoverBucket(figure: HTMLElement, index: number) {
  const x = Number(figure.querySelectorAll('.recharts-line-dots circle')[index].getAttribute('cx'))
  const surface = figure.querySelector('.recharts-wrapper') as HTMLElement
  fireEvent.mouseMove(surface, { clientX: x, clientY: 150, pageX: x, pageY: 150 })
}

const REGIONS = ['中部', '北部', '南部', '東部']

function regionalSeries(missing: Record<string, number[]>) {
  const instants = ['2026-09-09T19:40:00+08:00', '2026-09-09T19:50:00+08:00', '2026-09-09T20:00:00+08:00']
  return {
    timezone: 'Asia/Taipei',
    bucket: 'raw',
    agg: null,
    series: REGIONS.map((region) => ({
      field: 'load_mw',
      unit: 'MW',
      group: { region },
      points: instants.map((t, index) => ({ t, v: missing[region]?.includes(index) ? null : 9000 })),
    })),
  }
}

function captureRegionalSeries(missing: Record<string, number[]>) {
  const requests: URL[] = []
  server.use(
    http.get('*/data/power/regional/series', ({ request }) => {
      requests.push(new URL(request.url))
      return HttpResponse.json(regionalSeries(missing))
    }),
  )
  return requests
}

describe('Regional supply-demand chart', () => {
  it('draws one line per region and sends only the filters the series accepts', async () => {
    const requests = captureRegionalSeries({})
    renderPath(`${REGIONAL}?${WINDOW}&region=${encodeURIComponent('北部')}&completeness=incomplete`)

    await screen.findByRole('figure', {
      name: chart.figureLabel(m.explorer.datasets.regional_supply_demand.label, fields.load_mw, REGIONS.join('、')),
    })
    const params = requests.at(-1)!.searchParams
    expect(params.getAll('fields')).toEqual(['load_mw'])
    expect(params.get('region')).toBe('北部')
    expect(params.has('completeness')).toBe(false)
  })

  it('marks buckets where only some regions are missing in amber rather than gray', async () => {
    captureRegionalSeries({ 東部: [0], 中部: [1], 北部: [1], 南部: [1] })
    renderPath(`${REGIONAL}?${WINDOW}`)
    const figure = await screen.findByRole('figure')

    expect(await within(figure).findByText(chart.incompleteLegend)).toBeInTheDocument()
    expect(within(figure).queryByText(chart.gapLegend)).toBeNull()
  })

  it('keeps the gray gap band for buckets where every region is missing', async () => {
    captureRegionalSeries({ 東部: [1], 中部: [1], 北部: [1], 南部: [1] })
    renderPath(`${REGIONAL}?${WINDOW}`)
    const figure = await screen.findByRole('figure')

    expect(await within(figure).findByText(chart.gapLegend)).toBeInTheDocument()
    expect(within(figure).queryByText(chart.incompleteLegend)).toBeNull()
  })
})
