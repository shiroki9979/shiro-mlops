import { afterEach, expect, it, vi } from 'vitest'
import { defaultWindow, fromRfc3339, toRfc3339 } from '@/lib/data-explorer'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllEnvs()
})

it('defaults the explorer window to Taipei time in a Taipei browser', () => {
  vi.stubEnv('TZ', 'Asia/Taipei')
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-09-27T12:00:00Z'))

  expect(defaultWindow()).toEqual({
    start: '2026-09-26T20:00',
    end: '2026-09-27T20:00',
  })
})

it.each([
  ['2026-11-22T00:00:00+08:00', '2026-11-22T00:00'],
  ['2026-11-22T00:00:00Z', '2026-11-22T08:00'],
  ['2026-11-21T16:00:00Z', '2026-11-22T00:00'],
  ['2026-11-22T00:00:00+09:00', '2026-11-21T23:00'],
  ['2026-11-21T19:30:00-05:00', '2026-11-22T08:30'],
  ['2026-11-22T00:00:00.250+08:00', '2026-11-22T00:00'],
  ['2026-11-22T00:00:00z', '2026-11-22T08:00'],
])('shows %s in the window input as Taipei time %s', (value, shown) => {
  // The input is labelled Taipei time, and the API reads the offset the URL carries.
  expect(fromRfc3339(value)).toBe(shown)
})

it.each([
  ['2026-11-22T00:00:00', '2026-11-22T00:00'],
  ['2026-11-22T00:00', '2026-11-22T00:00'],
])('keeps %s, which has no offset, as the Taipei time the API reads it as', (value, shown) => {
  expect(fromRfc3339(value)).toBe(shown)
})

it.each([undefined, null, ''])('shows an empty input for %s', (value) => {
  expect(fromRfc3339(value)).toBe('')
})

it('leaves an unparseable value for the API to reject instead of hiding it', () => {
  expect(fromRfc3339('not-a-time+08:00')).toBe('not-a-time')
})

it('writes a typed window edge with the Taipei offset and reads it back unchanged', () => {
  expect(toRfc3339('2026-11-22T08:30')).toBe('2026-11-22T08:30:00+08:00')
  expect(fromRfc3339(toRfc3339('2026-11-22T08:30'))).toBe('2026-11-22T08:30')
  expect(toRfc3339('')).toBe('')
})
