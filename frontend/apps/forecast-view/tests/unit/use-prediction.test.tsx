import React from 'react'
import { describe, expect, it } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { usePrediction } from '@/hooks/use-prediction'
import { generateMockPredictions } from '@/mocks/handlers'
import { server } from '@/mocks/server'

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

describe('usePrediction Hook with MSW', () => {
  it('fetches prediction data successfully', async () => {
    const { result } = renderHook(() => usePrediction({ horizon_hours: 12 }), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(result.current.data?.status).toBe('success')
    expect(result.current.data?.predictions.length).toBe(12)
    expect(result.current.data?.subject).toBe('nationwide')
  })

  it('does not send the deprecated location field', async () => {
    let requestBody: Record<string, unknown> | undefined
    server.use(
      http.post('*/predict', async ({ request }) => {
        requestBody = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(generateMockPredictions(1))
      }),
    )
    const { result } = renderHook(() => usePrediction({ horizon_hours: 1 }), {
      wrapper: createWrapper(),
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(requestBody).toEqual({ horizon_hours: 1 })
  })
})
