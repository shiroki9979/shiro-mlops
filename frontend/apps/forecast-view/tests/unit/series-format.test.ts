import { describe, expect, it } from 'vitest'
import { formatSeriesValue } from '@/components/dashboard/series-format'

describe('forecast chart tooltip values', () => {
  it('labels predicted load with its unit', () => {
    expect(formatSeriesValue('predicted_load_mw', 31234.56, 'en')).toBe('31,234.6 MW')
  })

  it('shows an unplotted field as a plain number rather than guessing a unit', () => {
    expect(formatSeriesValue('residual', 1234.5, 'zh-TW')).toBe('1,234.5')
  })
})
