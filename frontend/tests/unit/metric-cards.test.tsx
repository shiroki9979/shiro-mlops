import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MetricCards } from '@/components/dashboard/metric-cards'

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
    expect(screen.getByText('尖峰用電預估')).toBeInTheDocument()
    expect(screen.getByText('區間平均負載')).toBeInTheDocument()
    expect(screen.getByText('離峰用電低谷')).toBeInTheDocument()
    expect(screen.getByText('最高預估氣溫')).toBeInTheDocument()

    // Peak is 35,000.0
    expect(screen.getByText('35,000.0')).toBeInTheDocument()
    // Avg is 30,000.0
    expect(screen.getByText('30,000.0')).toBeInTheDocument()
    // Min is 25,000.0
    expect(screen.getByText('25,000.0')).toBeInTheDocument()
    // Max Temp is 34.5°C
    expect(screen.getByText('34.5°C')).toBeInTheDocument()
  })
})
