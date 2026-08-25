import React from 'react'
import { describe, expect, it } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { usePrediction } from '@/hooks/use-prediction'

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
    expect(result.current.data?.location).toBe('Taipei')
  })
})
