import { afterEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
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
