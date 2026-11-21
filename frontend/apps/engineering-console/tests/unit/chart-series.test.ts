import { describe, expect, it } from 'vitest'
import { gapRanges, toChartRows, type PlottedSeries } from '@/components/data-explorer/chart-series'

const HOUR = 3_600_000
const at = (hour: number) => `2026-09-09T${String(hour).padStart(2, '0')}:00:00+08:00`
const instant = (hour: number) => Date.parse(at(hour))

function plotted(key: string, values: (number | null)[]): PlottedSeries {
  return { key, name: key, color: '#22d3ee', unit: 'MW', points: values.map((v, hour) => ({ t: at(hour), v })) }
}

describe('chart series helpers', () => {
  it('bands a missing bucket from its start to the next bucket', () => {
    expect(gapRanges([plotted('s0', [1, null, null, 4])])).toEqual([{ from: instant(1), to: instant(3) }])
  })

  it('gives a trailing gap the width of the preceding step', () => {
    expect(gapRanges([plotted('s0', [1, 2, null])])).toEqual([{ from: instant(2), to: instant(2) + HOUR }])
  })

  it('merges overlapping gaps across series', () => {
    const ranges = gapRanges([plotted('s0', [1, null, 3, 4]), plotted('s1', [1, 2, null, 4])])
    expect(ranges).toEqual([{ from: instant(1), to: instant(3) }])
  })

  it('keeps a null value for a series without a point at a shared instant', () => {
    const rows = toChartRows([plotted('s0', [1, 2]), plotted('s1', [5])])
    expect(rows).toEqual([
      { t: instant(0), s0: 1, s1: 5 },
      { t: instant(1), s0: 2, s1: null },
    ])
  })
})
