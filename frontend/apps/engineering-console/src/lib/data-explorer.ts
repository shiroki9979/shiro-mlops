import { TAIPEI_TIME_ZONE } from '@shiro-mlops/shared/i18n/format'
import { ListEnvelope } from '@/schemas/data-explorer'

export function exportCsv(filename: string, rows: Array<Record<string, unknown>>): void {
  if (rows.length === 0) return
  const headers = Object.keys(rows[0])
  const csv = [
    headers.map(csvCell).join(','),
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(',')),
  ].join('\r\n')
  if (typeof URL.createObjectURL !== 'function') return
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function csvCell(value: unknown): string {
  const text = value !== null && typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')
  return `"${text.replaceAll('"', '""')}"`
}

export function toRfc3339(localValue: string): string {
  if (!localValue) return ''
  return localValue.length === 16 ? `${localValue}:00+08:00` : localValue
}

export function fromRfc3339(value?: string | null): string {
  if (!value) return ''
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
