import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
import { zhTW } from '@/i18n/zh-TW'

function renderSettings() {
  const history = createMemoryHistory({ initialEntries: ['/console/settings'] })
  return render(<RouterProvider router={createAppRouter(history)} />)
}

describe('Settings page', () => {
  it('shows the read-only API endpoint without hardcoded resiliency claims', async () => {
    renderSettings()

    expect(await screen.findByLabelText(zhTW.settings.connection.endpointLabel)).toHaveValue(
      zhTW.settings.connection.sameOriginProxy,
    )
    expect(screen.queryByText(/Resiliency/)).not.toBeInTheDocument()
    expect(screen.queryByText('3 次')).not.toBeInTheDocument()
    expect(screen.queryByText('Parquet / Local Snapshot')).not.toBeInTheDocument()
    expect(screen.queryByText('Fallback to Climatology Norm')).not.toBeInTheDocument()
  })

  it('does not describe cache or degraded-mode strategy as configurable', async () => {
    renderSettings()

    await screen.findByText(zhTW.settings.connection.endpointLabel)
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

    const horizonInput = await screen.findByLabelText(zhTW.settings.tester.horizonLabel)
    await user.clear(horizonInput)
    await user.type(horizonInput, '6')
    const submitButton = screen.getByRole('button', { name: zhTW.settings.tester.submit })
    await user.click(submitButton)

    expect(submitButton).toBeDisabled()
    releaseResponse()

    expect(await screen.findByText(zhTW.settings.tester.success)).toBeInTheDocument()
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

    await user.click(await screen.findByRole('button', { name: zhTW.settings.tester.submit }))

    expect(await screen.findByText(zhTW.settings.tester.failure)).toBeInTheDocument()
    expect(
      screen.getByText(zhTW.settings.tester.error('API Error (503): model unavailable')),
    ).toBeInTheDocument()
    expect(screen.queryByText(zhTW.settings.tester.success)).not.toBeInTheDocument()
  })
})
