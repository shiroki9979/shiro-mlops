import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { createAppRouter } from '@/router'
import { zhTW } from '@/i18n/zh-TW'

function renderAppAt(path: string) {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }))
  render(<RouterProvider router={router} />)
  return router
}

describe('Engineering Console shell', () => {
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
})
