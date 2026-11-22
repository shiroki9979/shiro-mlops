import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { createAppRouter } from '@/router'
import { server } from '@/mocks/server'
import { zhTW } from '@/i18n/zh-TW'

const m = zhTW
const results = m.explorer.results

function renderPath(path: string) {
  const history = createMemoryHistory({ initialEntries: [`/console${path}`] })
  return render(<RouterProvider router={createAppRouter(history)} />)
}

function envelope(item: Record<string, unknown>, missingSlots: string[]) {
  return {
    timezone: 'Asia/Taipei',
    items: [item],
    next_cursor: null,
    has_more: false,
    missing_slots: missingSlots,
  }
}

async function openGapList(slotCount: string) {
  const user = userEvent.setup()
  const toggle = await screen.findByRole('button', { name: results.gaps(slotCount) })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await user.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  return { user, list: screen.getByRole('region', { name: results.gapListTitle }) }
}

describe('Data Explorer gap list', () => {
  it('merges consecutive hourly-load gaps into ranges with their length', async () => {
    server.use(http.get('*/data/power/load', () => HttpResponse.json(envelope(
      { datetime: '2026-11-20T10:00:00+08:00', subject: 'nationwide', load_mw: 30000 },
      [
        '2026-11-20T03:00:00+08:00',
        '2026-11-20T04:00:00+08:00',
        '2026-11-20T05:00:00+08:00',
        '2026-11-20T08:00:00+08:00',
      ],
    ))))
    renderPath('/data/power/load?start=2026-11-20T00:00:00%2B08:00&end=2026-11-20T12:00:00%2B08:00')

    const { list } = await openGapList('4')

    expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      results.gapRange('11/20 03:00–05:00', results.gapHours('3')),
      results.gapRange('11/20 08:00', results.gapHours('1')),
    ])
  })

  it('merges regional gaps on the 10-minute cadence across midnight', async () => {
    server.use(http.get('*/data/power/regional', () => HttpResponse.json(envelope(
      { observed_at: '2026-11-16T21:00:00+08:00', region: '北部', load_mw: 10000 },
      [
        '2026-11-16T21:00:00+08:00',
        '2026-11-16T23:50:00+08:00',
        '2026-11-17T00:00:00+08:00',
        '2026-11-17T00:10:00+08:00',
        '2026-11-17T00:20:00+08:00',
        '2026-11-17T00:30:00+08:00',
        '2026-11-17T00:40:00+08:00',
        '2026-11-17T00:50:00+08:00',
      ],
    ))))
    renderPath('/data/power/regional?start=2026-11-16T20:00:00%2B08:00&end=2026-11-17T01:00:00%2B08:00')

    const { list } = await openGapList('8')

    expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      results.gapRange('11/16 21:00', results.gapMinutes('10')),
      results.gapRange('11/16 23:50–11/17 00:50', results.gapHoursMinutes('1', '10')),
    ])
  })

  it('groups station-observation gaps by station and leaves the window unchanged on click', async () => {
    server.use(http.get('*/data/weather/observations', () => HttpResponse.json(envelope(
      { observed_at: '2026-11-20T10:00:00+08:00', station_id: '466920', temperature_c: 20 },
      [
        '2026-11-20T03:00:00+08:00:466920',
        '2026-11-20T03:00:00+08:00:467490',
        '2026-11-20T04:00:00+08:00:466920',
        '2026-11-20T06:00:00+08:00:467490',
      ],
    ))))
    renderPath('/data/weather/observations?start=2026-11-20T00:00:00%2B08:00&end=2026-11-20T12:00:00%2B08:00')

    const { user, list } = await openGapList('4')

    const taipei = within(list).getByRole('list', { name: results.gapStation('466920') })
    const taichung = within(list).getByRole('list', { name: results.gapStation('467490') })
    expect(within(taipei).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      results.gapRange('11/20 03:00–04:00', results.gapHours('2')),
    ])
    expect(within(taichung).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      results.gapRange('11/20 03:00', results.gapHours('1')),
      results.gapRange('11/20 06:00', results.gapHours('1')),
    ])

    await user.click(within(taipei).getByRole('listitem'))
    expect(screen.getByLabelText(m.explorer.filters.start)).toHaveValue('2026-11-20T00:00')
    expect(screen.getByLabelText(m.explorer.filters.end)).toHaveValue('2026-11-20T12:00')
  })
})
