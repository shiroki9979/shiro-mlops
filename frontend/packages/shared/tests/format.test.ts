import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  formatDateTime,
  formatDecimal,
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

describe('formatter reuse', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('builds one Intl formatter per locale and options, however many values a table formats', async () => {
    // A fresh module starts with no formatter built, so the count is exact.
    vi.resetModules()
    const numberFormat = vi.spyOn(Intl, 'NumberFormat')
    const dateTimeFormat = vi.spyOn(Intl, 'DateTimeFormat')
    const format = await import('../src/i18n/format')

    for (let row = 0; row < 200; row += 1) {
      for (const locale of ['zh-TW', 'en'] as const) {
        format.formatLoadMW(30000 + row, locale)
        format.formatTimestamp(NOON_UTC, locale)
      }
    }

    expect(numberFormat).toHaveBeenCalledTimes(2)
    expect(dateTimeFormat).toHaveBeenCalledTimes(2)
  })

  it('keeps each locale and each set of options to its own output when calls interleave', () => {
    const outputs = () => [
      plainSpaces(formatDateTime(NOON_UTC, 'zh-TW')),
      plainSpaces(formatDateTime(NOON_UTC, 'en')),
      plainSpaces(formatTimestamp(NOON_UTC, 'zh-TW')),
      plainSpaces(formatTimestamp(NOON_UTC, 'en')),
      formatDecimal(1.5, 'en', 1),
      formatDecimal(1.5, 'en', 3),
      formatPercent(2.1, 'zh-TW', 2),
      formatPercent(2.1, 'zh-TW', 1),
      formatPercentDelta(2.1, 'zh-TW', 1),
    ]
    const expected = [
      '09/09 20:00',
      '09/09, 20:00',
      '2026/09/09 20:00:00',
      '09/09/2026, 20:00:00',
      '1.5',
      '1.500',
      '2.10%',
      '2.1%',
      '+2.1%',
    ]

    expect(outputs()).toEqual(expected)
    expect(outputs()).toEqual(expected)
  })
})
