import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { createAppRouter } from '@/router'
import { zhTW } from '@/i18n/zh-TW'

describe('Forecast View shell', () => {
  // Nothing on the read-only Forecast View raises a toast, so a toast container would be an empty
  // live region for screen readers and unused code in the public bundle.
  it('mounts no toast notification region', async () => {
    render(<RouterProvider router={createAppRouter(createMemoryHistory({ initialEntries: ['/'] }))} />)
    expect(await screen.findByLabelText(zhTW.localeSwitcher.label)).toBeInTheDocument()

    expect(screen.queryByRole('region', { name: /notifications/i })).not.toBeInTheDocument()
  })
})
