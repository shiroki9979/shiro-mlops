import { TAIPEI_TIME_ZONE } from '@shiro-mlops/shared/i18n/format'
import { ListEnvelope } from '@/schemas/data-explorer'

export function toRfc3339(localValue: string): string {
  if (!localValue) return ''
  return localValue.length === 16 ? `${localValue}:00+08:00` : localValue
}

const HAS_UTC_OFFSET = /([zZ]|[+-]\d{2}:\d{2})$/

// The window inputs are labelled Taipei time. A URL may carry another offset (a pasted
// `...Z` link); the API reads that offset, so the input shows the same instant in Taipei
// time rather than the digits as written. A value with no offset is Taipei time already.
export function fromRfc3339(value?: string | null): string {
  if (!value) return ''
  const instant = HAS_UTC_OFFSET.test(value) ? new Date(value) : null
  if (instant && !Number.isNaN(instant.getTime())) return toDatetimeLocal(instant)
  return value.replace('+08:00', '').slice(0, 16)
}

export function defaultWindow(hours = 24, lookAheadHours = 0): { start: string; end: string } {
  const now = new Date()
  const start = new Date(now.getTime() - hours * 3600_000)
  const end = new Date(now.getTime() + lookAheadHours * 3600_000)
  return { start: toDatetimeLocal(start), end: toDatetimeLocal(end) }
}

export function toDatetimeLocal(value: Date): string {
  const taipei = new Date(value.getTime() + 8 * 3600_000)
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${taipei.getUTCFullYear()}-${pad(taipei.getUTCMonth() + 1)}-${pad(taipei.getUTCDate())}T${pad(taipei.getUTCHours())}:${pad(taipei.getUTCMinutes())}`
}

const TAIPEI_DAY_FORMAT = new Intl.DateTimeFormat('en-CA', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  timeZone: TAIPEI_TIME_ZONE,
})

// Date separator rows follow the Taipei day the data is labelled in, not the viewer's local day.
export function taipeiCalendarDate(timestamp: string): string | null {
  const instant = new Date(timestamp)
  if (Number.isNaN(instant.getTime())) return null
  const parts = Object.fromEntries(TAIPEI_DAY_FORMAT.formatToParts(instant).map((part) => [part.type, part.value]))
  return `${parts.year}-${parts.month}-${parts.day}`
}

export type { ListEnvelope }
