import { afterEach, expect, it, vi } from 'vitest'
import { defaultWindow } from '@/lib/data-explorer'

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
