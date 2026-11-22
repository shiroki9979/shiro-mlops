import { cn } from '@shiro-mlops/shared/utils'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@shiro-mlops/shared/ui/table'
import { formatCalendarDate } from '@shiro-mlops/shared/i18n/format'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'
import { taipeiCalendarDate } from '@/lib/data-explorer'
import type { ExplorerFieldKey } from './catalog'
import { explorerCellClass, explorerCellPresentation } from './cell-presentation'
import { ExplorerCellValue } from './explorer-cell'
import { explorerFieldKind, explorerFieldLabel, formatExplorerField } from './field-format'

type ExplorerRow = Record<string, unknown>

interface ExplorerTableProps {
  columns: ExplorerFieldKey[]
  rows: ExplorerRow[]
  onSelect: (row: ExplorerRow) => void
}

// Compact density and the sticky header apply only here; the shared table defaults stay as Forecast View uses them.
const SCROLL_AREA = 'max-h-[70vh]'
const HEAD_CLASS = 'sticky top-0 z-10 h-8 px-3 bg-slate-900 shadow-[inset_0_-1px_0_var(--color-slate-800)]'
const CELL_CLASS = 'px-3 py-1.5 text-xs'

type TableLine =
  | { kind: 'record'; row: ExplorerRow; index: number }
  | { kind: 'daySeparator'; day: string; index: number }

export function ExplorerTable({ columns, rows, onSelect }: ExplorerTableProps) {
  const m = useMessages()
  const locale = useLocale()
  return (
    <Table containerClassName={SCROLL_AREA}>
      <TableHeader>
        <TableRow>
          {columns.map((column) => (
            <TableHead key={column} className={cn(HEAD_CLASS, isNumberColumn(column) && 'text-right')}>
              {explorerFieldLabel(column, m)}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {withDaySeparators(rows, columns[0]).map((line) =>
          line.kind === 'daySeparator' ? (
            <TableRow key={`day-before-${line.index}`} className="hover:bg-transparent">
              <TableCell colSpan={columns.length} className="bg-slate-950/40 px-3 py-1 text-xs font-semibold text-slate-400">
                {formatCalendarDate(line.day, locale)}
              </TableCell>
            </TableRow>
          ) : (
            <TableRow key={line.index} className="cursor-pointer" onClick={() => onSelect(line.row)}>
              {columns.map((column) => (
                <TableCell key={column} className={cn(CELL_CLASS, explorerCellClass(column))}>
                  <ExplorerCellValue
                    column={column}
                    value={line.row[column]}
                    text={formatExplorerField(column, line.row[column], { locale, m })}
                  />
                </TableCell>
              ))}
            </TableRow>
          ),
        )}
      </TableBody>
    </Table>
  )
}

// Separators mark only day changes between neighbours; the first row needs none because the window shows its day.
function withDaySeparators(rows: ExplorerRow[], timeColumn: ExplorerFieldKey | undefined): TableLine[] {
  const lines: TableLine[] = []
  let previousDay: string | null = null
  rows.forEach((row, index) => {
    const day = rowDay(row, timeColumn)
    if (previousDay !== null && day !== null && day !== previousDay) lines.push({ kind: 'daySeparator', day, index })
    if (day !== null) previousDay = day
    lines.push({ kind: 'record', row, index })
  })
  return lines
}

function isNumberColumn(column: ExplorerFieldKey): boolean {
  return explorerCellPresentation(column) === 'number'
}

function rowDay(row: ExplorerRow, timeColumn: ExplorerFieldKey | undefined): string | null {
  if (!timeColumn || explorerFieldKind(timeColumn) !== 'timestamp') return null
  const value = row[timeColumn]
  return typeof value === 'string' ? taipeiCalendarDate(value) : null
}
