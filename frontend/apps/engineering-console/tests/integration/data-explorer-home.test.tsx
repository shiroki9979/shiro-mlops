import { afterEach, describe, expect, it } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { onlineManager } from '@tanstack/react-query'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
import { zhTW } from '@/i18n/zh-TW'

const m = zhTW
const loadLabel = m.explorer.datasets.hourly_load.label

function renderPath(path: string) {
  const history = createMemoryHistory({ initialEntries: [`/console${path}`] })
  render(<RouterProvider router={createAppRouter(history)} />)
}

afterEach(() => {
  onlineManager.setOnline(true)
})

describe('Data Explorer home dataset status', () => {
  it('shows an empty dataset as no data, without freshness, completeness or timestamps', async () => {
    server.use(
      http.get('*/data/status', () =>
        HttpResponse.json({
          timezone: 'Asia/Taipei',
          datasets: [{ kind: 'empty', id: 'hourly_load', label: loadLabel, overall: 'warning', href: '/data/power/load' }],
        }),
      ),
    )

    renderPath('/data')

    const card = (await screen.findByRole('heading', { name: loadLabel })).closest('div.rounded-xl') as HTMLElement
    expect(within(card).getByText(m.status.overall.warning)).toBeInTheDocument()
    expect(within(card).getByText(m.status.empty)).toBeInTheDocument()
    expect(within(card).queryByText(new RegExp(m.status.freshnessLabel))).not.toBeInTheDocument()
    expect(within(card).queryByText(new RegExp(m.status.completenessLabel))).not.toBeInTheDocument()
    expect(within(card).queryByText(/最新來源時間|最新入庫時間|經過時間/)).not.toBeInTheDocument()
    expect(within(card).getByRole('link', { name: m.explorer.statusCard.openDetails })).toBeInTheDocument()
  })

  it('shows a populated dataset by its overall, freshness and completeness only', async () => {
    renderPath('/data')

    const card = (await screen.findByRole('heading', { name: loadLabel })).closest('div.rounded-xl') as HTMLElement
    expect(within(card).getByText(m.status.overall.warning)).toBeInTheDocument()
    expect(within(card).getByText(m.common.labeled(m.status.freshnessLabel, m.status.freshness.fresh))).toBeInTheDocument()
    expect(
      within(card).getByText(m.common.labeled(m.status.completenessLabel, m.status.completeness.incomplete)),
    ).toBeInTheDocument()
    expect(within(card).queryByText(m.status.empty)).not.toBeInTheDocument()
    expect(within(card).getByText(m.explorer.statusCard.ingestionAge('120'))).toBeInTheDocument()
  })

  it('keeps the status cards and notes the failed refresh when a later status read fails', async () => {
    const user = userEvent.setup()
    renderPath('/data/power/load')
    const main = await screen.findByRole('main')
    await within(main).findByRole('heading', { name: m.explorer.datasetStatus.title })

    let failedReads = 0
    server.use(
      http.get('*/data/status', () => {
        failedReads += 1
        return new HttpResponse(null, { status: 503 })
      }),
    )
    await user.click(within(main).getByRole('button', { name: m.common.refresh }))
    // The refetch and its one retry.
    await waitFor(() => expect(failedReads).toBe(2), { timeout: 3000 })

    await user.click(within(main).getByRole('link', { name: m.explorer.title }))

    expect(await screen.findByText(m.explorer.statusRefreshFailed)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: loadLabel })).toBeInTheDocument()
    expect(screen.queryByText(m.explorer.statusError)).not.toBeInTheDocument()
  })

  it('shows the read failure for the status and every preview while offline, then reads once back online', async () => {
    let statusReads = 0
    server.use(
      http.get('*/data/status', async () => {
        statusReads += 1
        return HttpResponse.json({
          timezone: 'Asia/Taipei',
          datasets: [
            {
              id: 'hourly_load',
              label: loadLabel,
              kind: 'populated',
              freshness: 'fresh',
              completeness: 'complete',
              overall: 'healthy',
              latest_source_at: '2026-09-09T20:00:00+08:00',
              latest_ingested_at: '2026-09-09T20:01:00+08:00',
              ingestion_age_seconds: 120,
              source_age_seconds: 180,
              missing_identifiers: [],
              latest_release_stale: null,
              href: '/data/power/load',
            },
          ],
        })
      }),
    )
    onlineManager.setOnline(false)

    renderPath('/data')

    expect(await screen.findByText(m.explorer.statusError)).toBeInTheDocument()
    expect(screen.queryByText(m.explorer.loadingStatus)).not.toBeInTheDocument()
    expect(statusReads).toBe(0)

    act(() => onlineManager.setOnline(true))

    expect(await screen.findByRole('heading', { name: loadLabel })).toBeInTheDocument()
    expect(screen.queryByText(m.explorer.statusError)).not.toBeInTheDocument()
    expect(statusReads).toBe(1)
  })

  it('shows the previews as failed while offline over a loaded status, then draws them once back online', async () => {
    const user = userEvent.setup()
    renderPath('/data/power/load')
    const main = await screen.findByRole('main')
    await within(main).findByRole('heading', { name: m.explorer.datasetStatus.title })
    onlineManager.setOnline(false)

    await user.click(within(main).getByRole('link', { name: m.explorer.title }))

    // Every dataset in the mock status has a preview, and none may be read while offline.
    await waitFor(() => expect(screen.getAllByText(m.explorer.sparkline.failed)).toHaveLength(6))
    expect(screen.queryByText(m.explorer.sparkline.loading)).not.toBeInTheDocument()
    expect(screen.queryByText(m.explorer.statusError)).not.toBeInTheDocument()

    act(() => onlineManager.setOnline(true))

    await waitFor(() => expect(screen.queryByText(m.explorer.sparkline.failed)).not.toBeInTheDocument())
  })
})
