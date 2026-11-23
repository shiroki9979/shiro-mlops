import { afterEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { onlineManager } from '@tanstack/react-query'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
import { zhTW } from '@/i18n/zh-TW'

function renderSettings() {
  const history = createMemoryHistory({ initialEntries: ['/console/settings'] })
  return render(<RouterProvider router={createAppRouter(history)} />)
}

const predictionPayload = (horizon_hours: number) => ({
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

describe('Settings page', () => {
  afterEach(() => {
    onlineManager.setOnline(true)
  })

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
        return HttpResponse.json(predictionPayload(horizon_hours))
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

  it('clears the previous failure while a re-submitted prediction is pending', async () => {
    let releaseRetry: () => void = () => {}
    const retryGate = new Promise<void>((resolve) => {
      releaseRetry = resolve
    })
    let attempt = 0
    server.use(
      http.post('*/predict', async () => {
        attempt += 1
        if (attempt === 1) {
          return HttpResponse.json({ detail: 'model unavailable' }, { status: 503 })
        }
        await retryGate
        return HttpResponse.json(predictionPayload(24))
      }),
    )
    const user = userEvent.setup()
    renderSettings()
    const submitButton = await screen.findByRole('button', { name: zhTW.settings.tester.submit })
    const failureText = zhTW.settings.tester.error('API Error (503): model unavailable')

    await user.click(submitButton)
    expect(await screen.findByText(failureText)).toBeInTheDocument()

    await user.click(submitButton)

    expect(submitButton).toBeDisabled()
    expect(screen.queryByText(zhTW.settings.tester.failure)).not.toBeInTheDocument()
    expect(screen.queryByText(failureText)).not.toBeInTheDocument()
    releaseRetry()
    expect(await screen.findByText(zhTW.settings.tester.success)).toBeInTheDocument()
  })

  it('sends the manual prediction while the browser reports offline and shows the response', async () => {
    let requested = false
    server.use(
      http.post('*/predict', () => {
        requested = true
        return HttpResponse.json(predictionPayload(24))
      }),
    )
    const user = userEvent.setup()
    renderSettings()
    const submitButton = await screen.findByRole('button', { name: zhTW.settings.tester.submit })

    onlineManager.setOnline(false)
    await user.click(submitButton)

    expect(await screen.findByText(zhTW.settings.tester.success)).toBeInTheDocument()
    expect(requested).toBe(true)
    expect(submitButton).toBeEnabled()
    expect(screen.getByText(/27123\.4/)).toBeInTheDocument()
  })

  it('shows the failure when the API is unreachable while the browser reports offline', async () => {
    server.use(http.post('*/predict', () => HttpResponse.error()))
    const user = userEvent.setup()
    renderSettings()
    const submitButton = await screen.findByRole('button', { name: zhTW.settings.tester.submit })

    onlineManager.setOnline(false)
    await user.click(submitButton)

    expect(await screen.findByText(zhTW.settings.tester.failure)).toBeInTheDocument()
    expect(submitButton).toBeEnabled()
    expect(screen.queryByText(zhTW.settings.tester.success)).not.toBeInTheDocument()
  })
})
