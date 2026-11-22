import { describe, expect, it } from 'vitest'
import {
  AUDIT_STATUS_COLORS,
  CHART_SURFACE,
  FORECAST_VINTAGE_COLORS,
  REGION_COLORS,
  SERIES_COLORS,
  STATION_COLORS,
  UNIT_TYPE_COLORS,
  categoryColor,
} from '@/lib/chart-palette'

// WCAG 2.x relative luminance and contrast ratio, written out from the spec.
function luminance(hex: string): number {
  const channels = [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255)
  const [r, g, b] = channels.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (light + 0.05) / (dark + 0.05)
}

const palettes: Record<string, readonly string[]> = {
  series: SERIES_COLORS,
  region: Object.values(REGION_COLORS),
  unitType: Object.values(UNIT_TYPE_COLORS),
  station: Object.values(STATION_COLORS),
  auditStatus: Object.values(AUDIT_STATUS_COLORS),
  forecastVintage: FORECAST_VINTAGE_COLORS,
}

describe('chart palette', () => {
  it('matches the known WCAG ratio for white on black', () => {
    expect(contrast('#ffffff', '#000000')).toBeCloseTo(21, 5)
  })

  it.each(Object.entries(palettes))('keeps every %s colour at 3:1 or more on the dark card', (_name, colors) => {
    for (const color of colors) {
      expect(contrast(color, CHART_SURFACE), color).toBeGreaterThanOrEqual(3)
    }
  })

  it('covers the four regions and the twelve unit types', () => {
    expect(Object.keys(REGION_COLORS)).toEqual(['北部', '中部', '南部', '東部'])
    expect(Object.keys(UNIT_TYPE_COLORS).sort()).toEqual(
      [
        '儲能',
        '儲能負載(Energy Storage System Load)',
        '其它再生能源',
        '太陽能',
        '民營電廠-燃氣',
        '民營電廠-燃煤',
        '水力',
        '汽電共生',
        '燃料油',
        '燃氣',
        '燃煤',
        '風力',
      ].sort(),
    )
  })

  it('falls back to the series order for categories the palette does not name', () => {
    expect(categoryColor(REGION_COLORS, '東部', 0)).toBe(REGION_COLORS['東部'])
    expect(categoryColor(REGION_COLORS, 'unknown', 1)).toBe(SERIES_COLORS[1])
    expect(categoryColor(undefined, undefined, SERIES_COLORS.length)).toBe(SERIES_COLORS[0])
  })
})
