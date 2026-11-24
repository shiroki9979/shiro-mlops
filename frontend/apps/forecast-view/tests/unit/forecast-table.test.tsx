import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { NonEmptyArray } from '@shiro-mlops/shared/query-view'
import { ForecastTable } from '@/components/dashboard/forecast-table'
import type { ForecastStep } from '@/schemas/published'
import { zhTW } from '@/i18n/zh-TW'

const FIRST_HOUR = Date.parse('2026-11-20T11:00:00+08:00')

function steps(count: number): NonEmptyArray<ForecastStep> {
  return Array.from({ length: count }, (_, index) => ({
    target_hour: new Date(FIRST_HOUR + index * 3_600_000).toISOString(),
    predicted_load_mw: 30000 + index,
  })) as NonEmptyArray<ForecastStep>
}

function bodyRows(): HTMLElement[] {
  return within(screen.getAllByRole('rowgroup')[1]).queryAllByRole('row')
}

async function goToLastPage(user: ReturnType<typeof userEvent.setup>) {
  const next = screen.getByRole('button', { name: zhTW.common.nextPage })
  while (!next.hasAttribute('disabled')) await user.click(next)
}

describe('ForecastTable paging', () => {
  it('stays on a page that exists when a refreshed forecast has fewer steps', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<ForecastTable steps={steps(168)} issuedAt="2026-11-20T10:15:00+08:00" />)
    await goToLastPage(user)
    expect(screen.getByText('17 / 17')).toBeInTheDocument()

    // The next hourly forecast reaches one anchor hour less far: 160 steps make 16 pages.
    rerender(<ForecastTable steps={steps(160)} issuedAt="2026-11-20T11:15:00+08:00" />)

    expect(screen.getByText('16 / 16')).toBeInTheDocument()
    expect(bodyRows()).toHaveLength(10)
    expect(screen.getByText(zhTW.dashboard.table.range(151, 160, 160))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: zhTW.common.nextPage })).toBeDisabled()
  })

  it('pages back from the clamped page to the one before it', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<ForecastTable steps={steps(168)} issuedAt="2026-11-20T10:15:00+08:00" />)
    await goToLastPage(user)
    rerender(<ForecastTable steps={steps(25)} issuedAt="2026-11-20T11:15:00+08:00" />)
    expect(screen.getByText('3 / 3')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: zhTW.common.previousPage }))

    expect(screen.getByText('2 / 3')).toBeInTheDocument()
    expect(screen.getByText(zhTW.dashboard.table.range(11, 20, 25))).toBeInTheDocument()
  })

  it('shows a single step on a single page with both paging buttons disabled', () => {
    render(<ForecastTable steps={steps(1)} issuedAt="2026-11-20T10:15:00+08:00" />)

    expect(screen.getByText('1 / 1')).toBeInTheDocument()
    expect(bodyRows()).toHaveLength(1)
    expect(screen.getByRole('button', { name: zhTW.common.previousPage })).toBeDisabled()
    expect(screen.getByRole('button', { name: zhTW.common.nextPage })).toBeDisabled()
  })

  it('ends the last page on a partial set of rows', async () => {
    const user = userEvent.setup()
    render(<ForecastTable steps={steps(23)} issuedAt="2026-11-20T10:15:00+08:00" />)

    await goToLastPage(user)

    expect(bodyRows()).toHaveLength(3)
    expect(screen.getByText(zhTW.dashboard.table.range(21, 23, 23))).toBeInTheDocument()
  })
})
