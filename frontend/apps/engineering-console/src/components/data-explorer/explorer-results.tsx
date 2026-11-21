import { Button } from '@shiro-mlops/shared/ui/button'
import { Card, CardContent } from '@shiro-mlops/shared/ui/card'
import { type Messages, useMessages } from '@/i18n/messages'
import type { ListEnvelope } from '@/schemas/data-explorer'
import type { ExplorerDatasetConfig } from './catalog'
import { ExplorerGapList } from './explorer-gap-list'
import { ExplorerTable } from './explorer-table'

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

function listErrorMessage(error: unknown, resultsText: Messages['explorer']['results']): string {
  const status = errorStatus(error)
  if (status === CURSOR_REJECTED_STATUS) return resultsText.cursorRejected
  if (status === INVALID_FILTERS_STATUS) return resultsText.invalidFilters
  if (status === DATABASE_UNAVAILABLE_STATUS) return resultsText.databaseUnavailable
  return resultsText.queryFailed
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
  const m = useMessages()
  const resultsText = m.explorer.results
  return (
    <Card>
      <CardContent className="pt-6">
        {isLoading ? (
          <p className="text-xs text-slate-500">{resultsText.loading}</p>
        ) : isError ? (
          <div>
            <p className="text-xs text-rose-300">{listErrorMessage(error, resultsText)}</p>
            {canRestart && isCursorRejected(error) && (
              <Button className="mt-4" variant="outline" onClick={onRestart}>{resultsText.backToFirstPage}</Button>
            )}
          </div>
        ) : !data || data.items.length === 0 ? (
          <p className="text-xs text-slate-500">{resultsText.empty}</p>
        ) : (
          <>
            <ExplorerGapList datasetId={dataset.id} missingSlots={data.missing_slots} />
            <ExplorerTable columns={dataset.columns} rows={data.items} onSelect={onSelect} />
            {data.has_more && (
              <Button
                className="mt-4"
                variant="outline"
                onClick={() => onNextPage(data.next_cursor ?? undefined)}
              >
                {m.common.nextPage}
              </Button>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
