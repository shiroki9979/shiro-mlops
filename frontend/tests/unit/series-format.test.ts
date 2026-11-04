import { describe, expect, it } from 'vitest'
import { formatSeriesValue } from '@/components/dashboard/series-format'

describe('forecast chart tooltip values', () => {
  it.each([
    ['predicted_load_mw', 31234.56, '31,234.6 MW'],
    ['temperature', 28.34, '28.3°C'],
    ['relative_humidity', 65, '65.0%'],
  ])('labels %s with its own unit', (dataKey, value, expected) => {
    expect(formatSeriesValue(dataKey, value, 'en')).toBe(expected)
  })

  it('shows an unplotted field as a plain number rather than guessing a unit', () => {
    expect(formatSeriesValue('residual', 1234.5, 'zh-TW')).toBe('1,234.5')
  })
})
