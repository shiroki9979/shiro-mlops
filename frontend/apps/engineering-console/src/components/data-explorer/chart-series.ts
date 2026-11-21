import { formatNumber } from '@shiro-mlops/shared/i18n/format'
import type { Locale } from '@shiro-mlops/shared/i18n/locale-store'
import type { Series } from '@/schemas/data-explorer'

// A series ready to draw: the container has already resolved its display name and colour,
// so chart-type renderers only lay out points.
export interface PlottedSeries {
  key: string
  field: string
  name: string
  color: string
  unit: string
  points: Series['points']
  // A second reading for the tooltip, e.g. MW also shown in Taipower's 萬瓩.
  tooltipAlternate?: TooltipAlternate
  // Set for datasets the API does not gap-fill: an instant without a point is no gap, so the line continues.
  connectNulls?: boolean
}

export interface TooltipAlternate {
  divisor: number
  format: (value: string) => string
}

// Gray bands mark buckets where no series has data; amber bands, where some series do and some do not.
export interface ChartBands {
  gaps: GapRange[]
  incomplete: GapRange[]
}

export type ChartRow = { t: number } & Record<string, number | null>

export interface GapRange {
  from: number
  to: number
}

// One row per bucket instant (epoch ms, so rows do not depend on the viewer's zone); a series
// without a point at that instant gets null, which breaks its line instead of bridging it.
export function toChartRows(series: PlottedSeries[]): ChartRow[] {
  const rows = new Map<number, ChartRow>()
  for (const item of series) {
    for (const point of item.points) {
      const t = Date.parse(point.t)
      const row = rows.get(t) ?? ({ t } as ChartRow)
      row[item.key] = point.v
      rows.set(t, row)
    }
  }
  const keys = series.map((item) => item.key)
  return [...rows.values()]
    .map((row) => ({ ...Object.fromEntries(keys.map((key) => [key, null])), ...row }) as ChartRow)
    .sort((a, b) => a.t - b.t)
}

// Each run of null buckets spans from its first bucket to the start of the next bucket; a run at
// the end of the series reuses the preceding step as its width. Overlapping runs merge.
export function gapRanges(series: PlottedSeries[]): GapRange[] {
  const ranges = series.flatMap((item) => nullRuns(item.points.map((point) => ({ t: Date.parse(point.t), v: point.v }))))
  return mergeRanges(ranges)
}

function nullRuns(points: { t: number; v: number | null }[]): GapRange[] {
  const sorted = [...points].sort((a, b) => a.t - b.t)
  const runs: GapRange[] = []
  let runStart: number | undefined
  sorted.forEach((point) => {
    if (point.v === null) {
      runStart ??= point.t
      return
    }
    if (runStart !== undefined) runs.push({ from: runStart, to: point.t })
    runStart = undefined
  })
  if (runStart !== undefined) runs.push({ from: runStart, to: trailingEnd(sorted) })
  return runs
}

function trailingEnd(sorted: { t: number }[]): number {
  const last = sorted[sorted.length - 1].t
  const previous = sorted.length > 1 ? sorted[sorted.length - 2].t : last
  return last + (last - previous)
}

function mergeRanges(ranges: GapRange[]): GapRange[] {
  const merged: GapRange[] = []
  for (const range of [...ranges].sort((a, b) => a.from - b.from)) {
    const last = merged[merged.length - 1]
    if (last && range.from <= last.to) last.to = Math.max(last.to, range.to)
    else merged.push({ ...range })
  }
  return merged
}

// Each bucket is classified across all series; a run of one class spans to the next bucket start.
export function bucketBands(series: PlottedSeries[]): ChartBands {
  const rows = toChartRows(series)
  const keys = series.map((item) => item.key)
  const bands: ChartBands = { gaps: [], incomplete: [] }
  rows.forEach((row, index) => {
    const nulls = keys.filter((key) => row[key] === null).length
    if (nulls === 0) return
    const target = nulls === keys.length ? bands.gaps : bands.incomplete
    const to = index + 1 < rows.length ? rows[index + 1].t : trailingEnd(rows)
    const last = target[target.length - 1]
    if (last && last.to === row.t) last.to = to
    else target.push({ from: row.t, to })
  })
  return bands
}

// Tooltips of every renderer show a value in its unit, then the alternate reading if the series has one.
export function formatSeriesValue(item: PlottedSeries, value: number, locale: Locale): string {
  const primary = `${formatNumber(value, locale)} ${item.unit}`
  const alternate = item.tooltipAlternate
  if (!alternate) return primary
  return `${primary}${alternate.format(formatNumber(value / alternate.divisor, locale))}`
}
