import { describe, expect, it } from 'vitest'
import { formatDateTime, formatLoadMW, formatTimestamp } from '@/i18n/format'

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
})
