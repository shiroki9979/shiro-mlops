import { describe, expect, it } from 'vitest'
import { formatExplorerField, explorerFieldLabel } from '@/components/data-explorer/field-format'
import { en } from '@/i18n/en'
import { zhTW } from '@/i18n/zh-TW'

function plainSpaces(text: string): string {
  return text.replace(/\s/g, ' ')
}

describe('formatExplorerField', () => {
  it.each([
    ['zh-TW', zhTW, '2026/09/09 20:00:00'],
    ['en', en, '09/09/2026, 20:00:00'],
  ] as const)('shows API timestamps as Taipei time for %s', (locale, messages, expected) => {
    const text = formatExplorerField('observed_at', '2026-09-09T20:00:00+08:00', { locale, messages })

    expect(plainSpaces(text)).toBe(expected)
  })

  it('groups measurement values with the locale separator', () => {
    const context = { locale: 'en', messages: en } as const

    expect(formatExplorerField('load_mw', 32100.5, context)).toBe('32,100.5')
    expect(formatExplorerField('curr_load_wan_kw', 3242.1, context)).toBe('3,242.1')
  })

  it('keeps identifiers and data values exactly as returned by the API', () => {
    const context = { locale: 'en', messages: en } as const

    expect(formatExplorerField('station_id', '466920', context)).toBe('466920')
    expect(formatExplorerField('geocode', '63000000', context)).toBe('63000000')
    expect(formatExplorerField('dataset_id', 'F-D0047-089', context)).toBe('F-D0047-089')
    expect(formatExplorerField('region', '北部', context)).toBe('北部')
    expect(formatExplorerField('missing_station_ids', ['466920', '467490'], context)).toBe('466920, 467490')
  })

  it.each([
    ['zh-TW', zhTW, '不完整', '否'],
    ['en', en, 'Incomplete', 'No'],
  ] as const)('translates audit status and flags for %s', (locale, messages, status, flag) => {
    expect(formatExplorerField('status', 'incomplete', { locale, messages })).toBe(status)
    expect(formatExplorerField('slot_complete', false, { locale, messages })).toBe(flag)
  })

  it('shows a dash for empty values and the raw text for fields it does not know', () => {
    const context = { locale: 'zh-TW', messages: zhTW } as const

    expect(formatExplorerField('load_mw', null, context)).toBe('—')
    expect(formatExplorerField('unexpected_field', 1234.5, context)).toBe('1234.5')
  })
})

describe('explorerFieldLabel', () => {
  it('labels known fields from the dictionary and falls back to the raw key', () => {
    expect(explorerFieldLabel('ingested_at', en)).toBe(en.explorer.fields.ingested_at)
    expect(explorerFieldLabel('ingested_at', zhTW)).toBe(zhTW.explorer.fields.ingested_at)
    expect(explorerFieldLabel('unexpected_field', en)).toBe('unexpected_field')
  })
})
