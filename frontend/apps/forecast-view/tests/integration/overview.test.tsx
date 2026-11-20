import React from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { OverviewPageForTest } from './test-helpers'
import { zhTW } from '@/i18n/zh-TW'

const dashboard = zhTW.dashboard

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
    expect(screen.getByText(dashboard.horizon.label)).toBeInTheDocument()
    expect(screen.getByText(dashboard.horizon.hours(24))).toBeInTheDocument()
    expect(screen.getByText(dashboard.horizon.hours(48))).toBeInTheDocument()
    expect(screen.getByText(dashboard.predictionSubject)).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()

    // Wait for MSW to respond and populate metrics
    await waitFor(() => {
      expect(screen.getByText(dashboard.metrics.peakTitle)).toBeInTheDocument()
    })

    // Check Table content rendered
    expect(screen.getByText(dashboard.table.title(24))).toBeInTheDocument()
    expect(screen.getByText(zhTW.common.exportCsv)).toBeInTheDocument()
  })
})
