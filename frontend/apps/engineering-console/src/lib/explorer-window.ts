import { toDatetimeLocal } from './data-explorer'

export interface ExplorerWindow {
  start: string
  end: string
}

export type ShiftDirection = 'earlier' | 'later'

const SECOND_MS = 1000
const HOUR_MS = 3600 * SECOND_MS
const DAY_MS = 24 * HOUR_MS
const TAIPEI_OFFSET_MS = 8 * HOUR_MS

export const PAST_QUICK_RANGES = [
  'today',
  'last24Hours',
  'last7Days',
  'detailLimit',
  'last30Days',
  'last92Days',
] as const
// Forecast windows filter on valid time, which lies ahead of now.
export const FORWARD_QUICK_RANGES = ['next24Hours', 'next72Hours', 'next7Days', 'next14Days'] as const

export type QuickRangeId = (typeof PAST_QUICK_RANGES)[number] | (typeof FORWARD_QUICK_RANGES)[number]

const FORWARD_RANGE_MS: Record<(typeof FORWARD_QUICK_RANGES)[number], number> = {
  next24Hours: DAY_MS,
  next72Hours: 3 * DAY_MS,
  next7Days: 7 * DAY_MS,
  next14Days: 14 * DAY_MS,
}

export function quickRangeWindow(range: QuickRangeId, now: Date, detailLimitDays: number): ExplorerWindow {
  const nowMs = Math.floor(now.getTime() / SECOND_MS) * SECOND_MS
  switch (range) {
    case 'today':
      return taipeiDayOf(nowMs)
    case 'last24Hours':
      return windowBetween(nowMs - DAY_MS, nowMs)
    case 'last7Days':
      return windowBetween(nowMs - 7 * DAY_MS, nowMs)
    case 'last30Days':
      return windowBetween(nowMs - 30 * DAY_MS, nowMs)
    case 'last92Days':
      return windowBetween(nowMs - 92 * DAY_MS, nowMs)
    case 'detailLimit':
      return windowBetween(nowMs - detailLimitDays * DAY_MS, nowMs)
    default:
      return windowBetween(nowMs, nowMs + FORWARD_RANGE_MS[range])
  }
}

// Windows are closed intervals, so the length counts the end second and the shifted window
// starts or ends one second away from the old one: adjacent, never overlapping.
export function shiftWindow(window: ExplorerWindow, direction: ShiftDirection): ExplorerWindow | null {
  const start = Date.parse(window.start)
  const end = Date.parse(window.end)
  if (Number.isNaN(start) || Number.isNaN(end)) return null
  const length = end - start + SECOND_MS
  return direction === 'earlier'
    ? windowBetween(start - length, start - SECOND_MS)
    : windowBetween(end + SECOND_MS, end + length)
}

export type ResolvedBucket = 'raw' | '1h' | '1d'

// Bucket instants on the chart, in epoch ms, in the order the pointer visited them.
export interface BucketSelection {
  from: number
  to: number
}

const BUCKET_SECONDS: Record<Exclude<ResolvedBucket, 'raw'>, number> = { '1h': 3600, '1d': 86400 }

// Each bucket instant labels the bucket's start, so the window runs from the first selected
// bucket's start to one second before the last selected bucket ends; Taipei has no DST, so a
// 1d bucket is always 24 hours.
export function brushWindow(
  selection: BucketSelection,
  bucket: ResolvedBucket,
  cadenceSeconds: number,
): ExplorerWindow {
  const bucketMs = (bucket === 'raw' ? cadenceSeconds : BUCKET_SECONDS[bucket]) * SECOND_MS
  const first = Math.min(selection.from, selection.to)
  const last = Math.max(selection.from, selection.to)
  return windowBetween(first, last + bucketMs - SECOND_MS)
}

// Same rule the list API applies before answering 422: a window of exactly `days` days is allowed.
export function exceedsDays(window: ExplorerWindow, days: number): boolean {
  return Date.parse(window.end) - Date.parse(window.start) > days * DAY_MS
}

function taipeiDayOf(epochMs: number): ExplorerWindow {
  const dayStart = Math.floor((epochMs + TAIPEI_OFFSET_MS) / DAY_MS) * DAY_MS - TAIPEI_OFFSET_MS
  return windowBetween(dayStart, dayStart + DAY_MS - SECOND_MS)
}

function windowBetween(startMs: number, endMs: number): ExplorerWindow {
  return { start: toTaipeiRfc3339(startMs), end: toTaipeiRfc3339(endMs) }
}

function toTaipeiRfc3339(epochMs: number): string {
  const date = new Date(epochMs)
  const seconds = String(date.getUTCSeconds()).padStart(2, '0')
  const millis = date.getUTCMilliseconds()
  const fraction = millis === 0 ? '' : `.${String(millis).padStart(3, '0')}`
  return `${toDatetimeLocal(date)}:${seconds}${fraction}+08:00`
}
