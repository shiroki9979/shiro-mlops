import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatNumber } from '@/i18n/format'
import { useLocale } from '@/i18n/locale-store'
import { type Messages, useMessages } from '@/i18n/use-messages'
import type { ListEnvelope } from '@/schemas/data-explorer'
import type { ExplorerDatasetConfig } from './catalog'
import { explorerFieldLabel, formatExplorerField } from './field-format'

interface ExplorerResultsProps {
  dataset: ExplorerDatasetConfig
  data?: ListEnvelope
  error: unknown
  isError: boolean
  isLoading: boolean
  canRestart: boolean
  onSelect: (row: Record<string, unknown>) => void
  onNextPage: (cursor: string | undefined) => void
  onRestart: () => void
}

const CURSOR_REJECTED_STATUS = 400
const INVALID_FILTERS_STATUS = 422
const DATABASE_UNAVAILABLE_STATUS = 503

function errorStatus(error: unknown): unknown {
  return typeof error === 'object' && error !== null && 'status' in error
    ? error.status
    : undefined
}

function isCursorRejected(error: unknown): boolean {
  return errorStatus(error) === CURSOR_REJECTED_STATUS
}

function listErrorMessage(error: unknown, text: Messages['explorer']['results']): string {
  const status = errorStatus(error)
  if (status === CURSOR_REJECTED_STATUS) return text.cursorRejected
  if (status === INVALID_FILTERS_STATUS) return text.invalidFilters
  if (status === DATABASE_UNAVAILABLE_STATUS) return text.databaseUnavailable
  return text.queryFailed
}

export function ExplorerResults({
  dataset,
  data,
  error,
  isError,
  isLoading,
  canRestart,
  onSelect,
  onNextPage,
  onRestart,
}: ExplorerResultsProps) {
  const messages = useMessages()
  const locale = useLocale()
  const text = messages.explorer.results
  return (
    <Card>
      <CardContent className="pt-6">
        {isLoading ? (
          <p className="text-xs text-slate-500">{text.loading}</p>
        ) : isError ? (
          <div>
            <p className="text-xs text-rose-300">{listErrorMessage(error, text)}</p>
            {canRestart && isCursorRejected(error) && (
              <Button className="mt-4" variant="outline" onClick={onRestart}>{text.backToFirstPage}</Button>
            )}
          </div>
        ) : !data || data.items.length === 0 ? (
          <p className="text-xs text-slate-500">{text.empty}</p>
        ) : (
          <>
            {data.missing_slots.length > 0 && (
              <p className="text-xs text-amber-300 mb-3">
                {text.gaps(formatNumber(data.missing_slots.length, locale))}
              </p>
            )}
            <Table>
              <TableHeader>
                <TableRow>
                  {dataset.columns.map((column) => (
                    <TableHead key={column}>{explorerFieldLabel(column, messages)}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((row, index) => (
                  <TableRow key={index} className="cursor-pointer" onClick={() => onSelect(row)}>
                    {dataset.columns.map((column) => (
                      <TableCell key={column} className="font-mono text-xs">
                        {formatExplorerField(column, row[column], { locale, messages })}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {data.has_more && (
              <Button
                className="mt-4"
                variant="outline"
                onClick={() => onNextPage(data.next_cursor ?? undefined)}
              >
                {messages.common.nextPage}
              </Button>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
