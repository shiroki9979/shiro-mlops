import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MetricCards } from '@/components/dashboard/metric-cards'
import { zhTW } from '@/i18n/zh-TW'

describe('MetricCards Component', () => {
  it('renders peak, avg, and valley metrics from the steps accurately', () => {
    render(
      <MetricCards
        steps={[
          { target_hour: '2026-08-25T12:00:00Z', predicted_load_mw: 35000 },
          { target_hour: '2026-08-25T13:00:00Z', predicted_load_mw: 25000 },
        ]}
      />,
    )

    // Check titles
    const metrics = zhTW.dashboard.metrics
    expect(screen.getByText(metrics.peakTitle)).toBeInTheDocument()
    expect(screen.getByText(metrics.averageTitle)).toBeInTheDocument()
    expect(screen.getByText(metrics.valleyTitle)).toBeInTheDocument()

    // Peak is 35,000.0
    expect(screen.getByText('35,000.0')).toBeInTheDocument()
    // Avg is 30,000.0
    expect(screen.getByText('30,000.0')).toBeInTheDocument()
    // Min is 25,000.0
    expect(screen.getByText('25,000.0')).toBeInTheDocument()
    // The peak at 12:00 UTC happens at 20:00 Taipei time, whatever the host time zone is.
    expect(screen.getByText(metrics.peakTime('08/25 20:00'))).toBeInTheDocument()
  })
})
