import { formatDateTime, formatNumber } from '@shiro-mlops/shared/i18n/format'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'
import { AUDIT_STATUS_COLORS, CHART_GRID } from '@/lib/chart-palette'
import type { Series } from '@/schemas/data-explorer'
import { translateCompleteness } from './status-text'

const HOUR_MS = 3600_000
const GRID_HOURS = 24
const COMPLETE = 'complete'
const INCOMPLETE = 'incomplete'

type CellStatus = typeof COMPLETE | typeof INCOMPLETE | 'none'

interface AuditStatusGridProps {
  // Hourly status counts (`bucket=1h`), one series per status.
  series: Series[]
  now: Date
  label: (summary: string) => string
}

// One cell per hour, the last being the current hour. An hour with any non-complete batch or
// version is incomplete; an hour without one is left empty, so a stalled fetch shows as a run of empty cells.
export function AuditStatusGrid({ series, now, label }: AuditStatusGridProps) {
  const m = useMessages()
  const locale = useLocale()
  const cells = statusCells(series, now)
  const statusText = (status: CellStatus) => (status === 'none' ? m.explorer.sparkline.noRecord : translateCompleteness(status, m))
  const summary = ([COMPLETE, INCOMPLETE, 'none'] as const)
    .map((status) => [status, cells.filter((cell) => cell.status === status).length] as const)
    .filter(([, hours]) => hours > 0)
    .map(([status, hours]) => m.explorer.sparkline.statusHours(statusText(status), formatNumber(hours, locale)))
    .join('、')

  return (
    <div role="img" aria-label={label(summary)} className="flex h-6 gap-0.5">
      {cells.map((cell) => (
        <span
          key={cell.hour}
          title={m.explorer.sparkline.cellTitle(formatDateTime(cell.hour, locale), statusText(cell.status))}
          className="flex-1 rounded-sm"
          style={{ backgroundColor: cellColor(cell.status), opacity: cell.status === 'none' ? 0.4 : 1 }}
        />
      ))}
    </div>
  )
}

function statusCells(series: Series[], now: Date): { hour: number; status: CellStatus }[] {
  const lastHour = Math.floor(now.getTime() / HOUR_MS) * HOUR_MS
  const hoursWith = (match: (status: string) => boolean) =>
    new Set(
      series
        .filter((item) => match(item.group.status))
        .flatMap((item) => item.points.filter((point) => (point.v ?? 0) > 0).map((point) => Date.parse(point.t))),
    )
  const incomplete = hoursWith((status) => status !== COMPLETE)
  const complete = hoursWith((status) => status === COMPLETE)
  return Array.from({ length: GRID_HOURS }, (_, index) => {
    const hour = lastHour - (GRID_HOURS - 1 - index) * HOUR_MS
    const status: CellStatus = incomplete.has(hour) ? INCOMPLETE : complete.has(hour) ? COMPLETE : 'none'
    return { hour, status }
  })
}

function cellColor(status: CellStatus): string {
  return status === 'none' ? CHART_GRID : AUDIT_STATUS_COLORS[status]
}
