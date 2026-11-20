import { describe, expect, it } from 'vitest'
import {
  formatDateTime,
  formatLoadDelta,
  formatLoadMW,
  formatLoadThousands,
  formatPercent,
  formatPercentDelta,
  formatTemperature,
  formatTimestamp,
} from '../src/i18n/format'

// 12:00 UTC is 20:00 in Taipei; a UTC runtime exposes any formatter that follows the host time zone.
const NOON_UTC = '2026-09-09T12:00:00Z'

// CLDR separates zh-TW date and time with a thin space; the assertions target the visible text.
function plainSpaces(text: string): string {
  return text.replace(/\s/g, ' ')
}

describe('locale-aware formatters', () => {
  it('runs under a UTC host so Taipei output cannot come from the environment', () => {
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('UTC')
  })

  it.each([
    ['zh-TW', '09/09 20:00'],
    ['en', '09/09, 20:00'],
  ] as const)('formats chart and table times in Taipei time for %s', (locale, expected) => {
    expect(plainSpaces(formatDateTime(NOON_UTC, locale))).toBe(expected)
  })

  it.each([
    ['zh-TW', '2026/09/09 20:00:00'],
    ['en', '09/09/2026, 20:00:00'],
  ] as const)('formats full timestamps in Taipei time for %s', (locale, expected) => {
    expect(plainSpaces(formatTimestamp(NOON_UTC, locale))).toBe(expected)
  })

  it('crosses midnight in Taipei rather than in UTC', () => {
    expect(plainSpaces(formatDateTime('2026-09-09T16:30:00Z', 'zh-TW'))).toBe('09/10 00:30')
  })

  it.each(['zh-TW', 'en'] as const)('groups load values with one decimal for %s', (locale) => {
    expect(formatLoadMW(32100.54, locale)).toBe('32,100.5')
  })

  it.each(['zh-TW', 'en'] as const)('groups temperatures with one decimal for %s', (locale) => {
    expect(formatTemperature(1234.56, locale)).toBe('1,234.6°C')
  })

  it.each(['zh-TW', 'en'] as const)('formats percentages with the requested decimals for %s', (locale) => {
    expect(formatPercent(96.8, locale, 1)).toBe('96.8%')
    expect(formatPercent(2.1, locale, 2)).toBe('2.10%')
  })

  it.each([
    [1.234, '+1.23%'],
    [-1.234, '-1.23%'],
    [0, '0.00%'],
    [-0.001, '0.00%'],
  ])('signs a percentage change of %d only when it is not zero', (value, expected) => {
    expect(formatPercentDelta(value, 'en', 2)).toBe(expected)
  })

  it.each([
    [1234.56, '+1,234.6'],
    [-1234.56, '-1,234.6'],
    [0, '0.0'],
  ])('signs a load change of %d only when it is not zero', (value, expected) => {
    expect(formatLoadDelta(value, 'zh-TW')).toBe(expected)
  })

  it.each(['zh-TW', 'en'] as const)('abbreviates load axis ticks to thousands for %s', (locale) => {
    expect(formatLoadThousands(28000, locale)).toBe('28.0k')
    expect(formatLoadThousands(1234567, locale)).toBe('1,234.6k')
  })
})
