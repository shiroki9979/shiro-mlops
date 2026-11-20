import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MetricCards } from '@/components/dashboard/metric-cards'
import { zhTW } from '@/i18n/zh-TW'

describe('MetricCards Component', () => {
  it('renders skeleton cards when loading', () => {
    const { container } = render(<MetricCards isLoading={true} predictions={undefined} />)
    const cards = container.querySelectorAll('.animate-pulse')
    expect(cards.length).toBe(4)
  })

  it('renders peak, avg, and valley metrics from predictions accurately', () => {
    const mockPredictions = [
      {
        datetime: '2026-08-25T12:00:00Z',
        predicted_load_mw: 35000,
        temperature: 34.5,
        relative_humidity: 60,
      },
      {
        datetime: '2026-08-25T13:00:00Z',
        predicted_load_mw: 25000,
        temperature: 28.0,
        relative_humidity: 75,
      },
    ]

    render(<MetricCards isLoading={false} predictions={mockPredictions} />)

    // Check titles
    const metrics = zhTW.dashboard.metrics
    expect(screen.getByText(metrics.peakTitle)).toBeInTheDocument()
    expect(screen.getByText(metrics.averageTitle)).toBeInTheDocument()
    expect(screen.getByText(metrics.valleyTitle)).toBeInTheDocument()
    expect(screen.getByText(metrics.maxTemperatureTitle)).toBeInTheDocument()

    // Peak is 35,000.0
    expect(screen.getByText('35,000.0')).toBeInTheDocument()
    // Avg is 30,000.0
    expect(screen.getByText('30,000.0')).toBeInTheDocument()
    // Min is 25,000.0
    expect(screen.getByText('25,000.0')).toBeInTheDocument()
    // Max Temp is 34.5°C
    expect(screen.getByText('34.5°C')).toBeInTheDocument()
    // The peak at 12:00 UTC happens at 20:00 Taipei time, whatever the host time zone is.
    expect(screen.getByText(metrics.peakTime('08/25 20:00'))).toBeInTheDocument()
  })
})
