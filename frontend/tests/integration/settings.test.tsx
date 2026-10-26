import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { routeTree } from '../../src/routeTree'
import { server } from '../../src/mocks/server'

function renderSettings() {
  const history = createMemoryHistory({ initialEntries: ['/settings'] })
  const router = createRouter({ routeTree, history })
  return render(<RouterProvider router={router} />)
}

describe('Settings page', () => {
  it('shows the read-only API endpoint without hardcoded resiliency claims', async () => {
    renderSettings()

    expect(await screen.findByLabelText('API Base Endpoint')).toHaveValue(
      '/api (same-origin proxy)',
    )
    expect(screen.queryByText(/Resiliency/)).not.toBeInTheDocument()
    expect(screen.queryByText('3 次')).not.toBeInTheDocument()
    expect(screen.queryByText('Parquet / Local Snapshot')).not.toBeInTheDocument()
    expect(screen.queryByText('Fallback to Climatology Norm')).not.toBeInTheDocument()
  })

  it('does not describe cache or degraded-mode strategy as configurable', async () => {
    renderSettings()

    await screen.findByText('API Base Endpoint')
    expect(screen.queryByText(/快取|降級/)).not.toBeInTheDocument()
  })

  it('submits a manual prediction and shows the successful response', async () => {
    let releaseResponse: () => void = () => {}
    const responseGate = new Promise<void>((resolve) => {
      releaseResponse = resolve
    })
    server.use(
      http.post('*/predict', async ({ request }) => {
        const { horizon_hours } = (await request.json()) as { horizon_hours: number }
        await responseGate
        return HttpResponse.json({
          status: 'success',
          horizon_hours,
          subject: 'nationwide',
          predictions: [
            {
              datetime: '2026-10-26T01:00:00+08:00',
              predicted_load_mw: 27123.4,
              temperature: 24.5,
              relative_humidity: 78,
            },
          ],
        })
      }),
    )
    const user = userEvent.setup()
    renderSettings()

    const horizonInput = await screen.findByLabelText('Horizon Hours (1-168)')
    await user.clear(horizonInput)
    await user.type(horizonInput, '6')
    const submitButton = screen.getByRole('button', { name: /Execute Prediction/ })
    await user.click(submitButton)

    expect(submitButton).toBeDisabled()
    releaseResponse()

    expect(await screen.findByText('200 OK')).toBeInTheDocument()
    expect(submitButton).toBeEnabled()
    const responseText = screen.getByText(/27123\.4/).textContent
    expect(responseText).toContain('"horizon_hours": 6')
  })

  it('shows the API error when the manual prediction fails', async () => {
    server.use(
      http.post('*/predict', () =>
        HttpResponse.json({ detail: 'model unavailable' }, { status: 503 }),
      ),
    )
    const user = userEvent.setup()
    renderSettings()

    await user.click(await screen.findByRole('button', { name: /Execute Prediction/ }))

    expect(await screen.findByText('Error')).toBeInTheDocument()
    expect(
      screen.getByText('推論執行錯誤: API Error (503): model unavailable'),
    ).toBeInTheDocument()
    expect(screen.queryByText('200 OK')).not.toBeInTheDocument()
  })
})
