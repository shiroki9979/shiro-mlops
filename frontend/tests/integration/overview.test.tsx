import React from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { OverviewPageForTest } from './test-helpers'

describe('Overview Page Integration Test', () => {
  it('renders horizon controls, metric cards, and prediction table after loading data', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <OverviewPageForTest />
      </QueryClientProvider>,
    )

    // Check Controls exist
    expect(screen.getByText('預測時效：')).toBeInTheDocument()
    expect(screen.getByText('24 小時')).toBeInTheDocument()
    expect(screen.getByText('48 小時')).toBeInTheDocument()
    expect(screen.getByText('Prediction subject: Nationwide')).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()

    // Wait for MSW to respond and populate metrics
    await waitFor(() => {
      expect(screen.getByText('尖峰用電預估')).toBeInTheDocument()
    })

    // Check Table content rendered
    expect(screen.getByText(/逐時推論特徵明細表/)).toBeInTheDocument()
    expect(screen.getByText('匯出 CSV')).toBeInTheDocument()
  })
})
