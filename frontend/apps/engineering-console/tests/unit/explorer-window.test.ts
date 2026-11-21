import { expect, it } from 'vitest'
import { type QuickRangeId, quickRangeWindow, shiftWindow } from '@/lib/explorer-window'

it('shifts a Taipei day back to the whole previous day without overlap', () => {
  const today = { start: '2026-11-21T00:00:00+08:00', end: '2026-11-21T23:59:59+08:00' }

  expect(shiftWindow(today, 'earlier')).toEqual({
    start: '2026-11-20T00:00:00+08:00',
    end: '2026-11-20T23:59:59+08:00',
  })
})

it('shifts a window forward so it starts one second after the old end', () => {
  const window = { start: '2026-11-20T10:00:00+08:00', end: '2026-11-20T16:00:00+08:00' }

  expect(shiftWindow(window, 'later')).toEqual({
    start: '2026-11-20T16:00:01+08:00',
    end: '2026-11-20T22:00:01+08:00',
  })
})

it('returns null when the window cannot be parsed', () => {
  expect(shiftWindow({ start: 'not-a-time', end: '2026-11-20T16:00:00+08:00' }, 'earlier')).toBeNull()
})

// 12:30:15.250 in Taipei; quick ranges ending now drop the sub-second part.
const NOW = new Date('2026-11-21T04:30:15.250Z')

it.each<[QuickRangeId, string, string]>([
  ['today', '2026-11-21T00:00:00+08:00', '2026-11-21T23:59:59+08:00'],
  ['last24Hours', '2026-11-20T12:30:15+08:00', '2026-11-21T12:30:15+08:00'],
  ['last7Days', '2026-11-14T12:30:15+08:00', '2026-11-21T12:30:15+08:00'],
  ['detailLimit', '2026-10-21T12:30:15+08:00', '2026-11-21T12:30:15+08:00'],
  ['next24Hours', '2026-11-21T12:30:15+08:00', '2026-11-22T12:30:15+08:00'],
  ['next72Hours', '2026-11-21T12:30:15+08:00', '2026-11-24T12:30:15+08:00'],
  ['next7Days', '2026-11-21T12:30:15+08:00', '2026-11-28T12:30:15+08:00'],
  ['next14Days', '2026-11-21T12:30:15+08:00', '2026-12-05T12:30:15+08:00'],
])('places the %s quick range for a 31-day detail limit', (range, start, end) => {
  expect(quickRangeWindow(range, NOW, 31)).toEqual({ start, end })
})

it('takes today from the Taipei calendar when the UTC date is still yesterday', () => {
  const justAfterTaipeiMidnight = new Date('2026-11-20T16:30:00Z')

  expect(quickRangeWindow('today', justAfterTaipeiMidnight, 7)).toEqual({
    start: '2026-11-21T00:00:00+08:00',
    end: '2026-11-21T23:59:59+08:00',
  })
})

it('sizes the detail-limit range by the dataset list limit', () => {
  expect(quickRangeWindow('detailLimit', NOW, 7)).toEqual({
    start: '2026-11-14T12:30:15+08:00',
    end: '2026-11-21T12:30:15+08:00',
  })
})
