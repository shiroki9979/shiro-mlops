import { cloneElement, type ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
import { zhTW } from '@/i18n/zh-TW'

vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('recharts')>()
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      cloneElement(children as ReactElement<{ width: number; height: number }>, { width: 800, height: 320 }),
  }
})

// No shipped dataset offers three units yet, so the national chart gains a temperature option here
// to exercise the two-unit rule through the real page.
vi.mock('@/components/data-explorer/catalog', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/data-explorer/catalog')>()
  const datasets = actual.EXPLORER_DATASETS.map((dataset) =>
    dataset.id === 'national_supply_demand' && dataset.chart
      ? {
          ...dataset,
          chart: {
            ...dataset.chart,
            fieldOptions: [...(dataset.chart.fieldOptions ?? []), { field: 'temperature_c' as const, unit: '°C' }],
          },
        }
      : dataset,
  )
  return {
    ...actual,
    EXPLORER_DATASETS: datasets,
    datasetById: (id: string) => datasets.find((dataset) => dataset.id === id)!,
  }
})

const m = zhTW
const chart = m.explorer.chart
const fields = m.explorer.fields
const WINDOW = `start=${encodeURIComponent('2026-09-09T00:00:00+08:00')}&end=${encodeURIComponent('2026-09-09T20:00:00+08:00')}`

function renderPath(path: string) {
  const history = createMemoryHistory({ initialEntries: [`/console${path}`] })
  const router = createAppRouter(history)
  render(<RouterProvider router={router} />)
  return router
}

describe('Chart field units', () => {
  it('disables fields of a third unit once two units are selected, and re-enables them after one is cleared', async () => {
    server.use(
      http.get('*/data/power/supply-demand/series', () =>
        HttpResponse.json({ timezone: 'Asia/Taipei', bucket: 'raw', agg: null, series: [] }),
      ),
    )
    const user = userEvent.setup()
    const router = renderPath(`/data/power/supply-demand?${WINDOW}`)
    await user.click(await screen.findByRole('button', { name: chart.fieldPicker }))

    expect(screen.getByRole('checkbox', { name: fields.temperature_c })).toBeEnabled()
    await user.click(screen.getByRole('checkbox', { name: fields.curr_util_rate_pct }))

    await waitFor(() => expect(screen.getByRole('checkbox', { name: fields.temperature_c })).toBeDisabled())
    expect(screen.getByRole('checkbox', { name: fields.fore_peak_resv_rate_pct })).toBeEnabled()
    expect(screen.getByRole('checkbox', { name: fields.fore_peak_dema_load_mw })).toBeEnabled()

    await user.click(screen.getByRole('checkbox', { name: fields.curr_util_rate_pct }))

    await waitFor(() => expect(screen.getByRole('checkbox', { name: fields.temperature_c })).toBeEnabled())
    expect(router.state.location.search).not.toHaveProperty('fields')
  })
})
