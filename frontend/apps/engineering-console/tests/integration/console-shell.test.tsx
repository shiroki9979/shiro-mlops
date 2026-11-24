import { afterEach, describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { onlineManager } from '@tanstack/react-query'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
import { zhTW } from '@/i18n/zh-TW'

function renderAppAt(path: string) {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }))
  render(<RouterProvider router={router} />)
  return router
}

const healthPayload = (model_loaded: boolean) => ({
  status: 'ok',
  version: '0.1.0',
  environment: 'local',
  model_loaded,
  data_explorer_enabled: true,
})

const serviceStatus = zhTW.serviceStatus

function sidebarStatusCard() {
  return screen.getByRole('region', { name: serviceStatus.label })
}

// The pulse is CSS only, so its class is all the DOM shows of it.
function livePulse(card: HTMLElement) {
  return card.querySelector('.animate-pulse')
}

describe('Engineering Console shell', () => {
  afterEach(() => {
    onlineManager.setOnline(true)
  })

  it('opens monitoring at the console root', async () => {
    const router = renderAppAt('/console/')

    expect(await screen.findByRole('heading', { name: zhTW.monitoring.title })).toBeInTheDocument()
    expect(router.history.location.pathname).toBe('/console/monitoring')
  })

  it('shows API health and links every page under the console base path', async () => {
    renderAppAt('/console/settings')

    expect(await screen.findByText(zhTW.header.apiHealthy('local', '0.1.0'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: zhTW.nav.monitoring })).toHaveAttribute('href', '/console/monitoring')
    expect(screen.getByRole('link', { name: zhTW.nav.settings })).toHaveAttribute('href', '/console/settings')
  })

  it('reports the API unreachable, not the model unloaded, while the browser is offline', async () => {
    onlineManager.setOnline(false)
    renderAppAt('/console/settings')

    expect(await screen.findByText(zhTW.header.apiUnreachable)).toBeInTheDocument()
    expect(screen.queryByText(zhTW.header.modelNotLoaded)).not.toBeInTheDocument()
  })

  it('reports the model unloaded only when the health response says so', async () => {
    server.use(http.get('*/health', () => HttpResponse.json(healthPayload(false))))
    renderAppAt('/console/settings')

    expect(await screen.findByText(zhTW.header.modelNotLoaded)).toBeInTheDocument()
    expect(screen.queryByText(zhTW.header.apiUnreachable)).not.toBeInTheDocument()
  })

  it('shows the sidebar status card healthy, with the live pulse, when the API answers with the model loaded', async () => {
    renderAppAt('/console/settings')
    expect(await screen.findByText(zhTW.header.apiHealthy('local', '0.1.0'))).toBeInTheDocument()

    const card = sidebarStatusCard()
    expect(within(card).getByText(serviceStatus.apiState.reachable)).toBeInTheDocument()
    expect(within(card).getByText(serviceStatus.modelState.loaded)).toBeInTheDocument()
    expect(livePulse(card)).not.toBeNull()
  })

  it('shows the model not loaded in the sidebar status card, without the live pulse', async () => {
    server.use(http.get('*/health', () => HttpResponse.json(healthPayload(false))))
    renderAppAt('/console/settings')
    expect(await screen.findByText(zhTW.header.modelNotLoaded)).toBeInTheDocument()

    const card = sidebarStatusCard()
    expect(livePulse(card)).toBeNull()
    expect(within(card).getByText(serviceStatus.apiState.reachable)).toBeInTheDocument()
    expect(within(card).getByText(serviceStatus.modelState.notLoaded)).toBeInTheDocument()
    expect(within(card).queryByText(serviceStatus.modelState.loaded)).not.toBeInTheDocument()
  })

  it('shows the API unreachable and the model unknown in the sidebar status card, without the live pulse', async () => {
    server.use(http.get('*/health', () => HttpResponse.error()))
    renderAppAt('/console/settings')
    // useHealth retries once, after TanStack's one-second default delay
    expect(await screen.findByText(zhTW.header.apiUnreachable, {}, { timeout: 3000 })).toBeInTheDocument()

    const card = sidebarStatusCard()
    expect(livePulse(card)).toBeNull()
    expect(within(card).getByText(serviceStatus.apiState.unreachable)).toBeInTheDocument()
    expect(within(card).getByText(serviceStatus.modelState.unknown)).toBeInTheDocument()
    expect(within(card).queryByText(serviceStatus.apiState.reachable)).not.toBeInTheDocument()
  })

  it('re-reads the data source status when the header Refresh is pressed on monitoring', async () => {
    // The status never goes stale on its own, and monitoring has no Refresh of its own:
    // without this the cards kept the state from when the console was opened.
    const user = userEvent.setup()
    let statusReads = 0
    server.use(
      http.get('*/data/status', () => {
        statusReads += 1
        return HttpResponse.json({ timezone: 'Asia/Taipei', datasets: [] })
      }),
    )
    renderAppAt('/console/monitoring')
    await waitFor(() => expect(statusReads).toBe(1))

    await user.click(screen.getByRole('button', { name: zhTW.common.refresh }))

    await waitFor(() => expect(statusReads).toBe(2))
  })

  it('does not read the data source status from a page that does not show it', async () => {
    const user = userEvent.setup()
    let statusReads = 0
    server.use(
      http.get('*/data/status', () => {
        statusReads += 1
        return HttpResponse.json({ timezone: 'Asia/Taipei', datasets: [] })
      }),
    )
    renderAppAt('/console/settings')
    expect(await screen.findByText(zhTW.header.apiHealthy('local', '0.1.0'))).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: zhTW.common.refresh }))

    await screen.findByText(zhTW.header.apiHealthy('local', '0.1.0'))
    expect(statusReads).toBe(0)
  })

  it('reports the API unreachable when a refresh fails after a healthy response', async () => {
    const user = userEvent.setup()
    renderAppAt('/console/settings')
    expect(await screen.findByText(zhTW.header.apiHealthy('local', '0.1.0'))).toBeInTheDocument()

    server.use(http.get('*/health', () => HttpResponse.error()))
    await user.click(screen.getByRole('button', { name: zhTW.common.refresh }))

    // useHealth retries once, after TanStack's one-second default delay
    expect(await screen.findByText(zhTW.header.apiUnreachable, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.queryByText(zhTW.header.apiHealthy('local', '0.1.0'))).not.toBeInTheDocument()
  })
})
