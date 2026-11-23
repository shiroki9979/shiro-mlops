import { Button } from '@shiro-mlops/shared/ui/button'
import { Card, CardContent } from '@shiro-mlops/shared/ui/card'
import { type Messages, useMessages } from '@/i18n/messages'
import type { DataExplorerError, DataExplorerErrorKind } from '@/lib/api-client'
import type { ListEnvelope } from '@/schemas/data-explorer'
import type { ExplorerDatasetConfig } from './catalog'
import { ExplorerGapList } from './explorer-gap-list'
import { ExplorerTable } from './explorer-table'

interface ExplorerResultsProps {
  dataset: ExplorerDatasetConfig
  data?: ListEnvelope
  error: DataExplorerError | null
  isError: boolean
  isLoading: boolean
  canRestart: boolean
  detailLimitExceeded: boolean
  onSelect: (row: Record<string, unknown>) => void
  onNextPage: (cursor: string | undefined) => void
  onRestart: () => void
}

function listErrorMessage(kind: DataExplorerErrorKind, resultsText: Messages['explorer']['results']): string {
  const messages: Record<DataExplorerErrorKind, string> = {
    cursorRejected: resultsText.cursorRejected,
    invalidQuery: resultsText.invalidFilters,
    databaseUnavailable: resultsText.databaseUnavailable,
    invalidResponse: resultsText.queryFailed,
    other: resultsText.queryFailed,
  }
  return messages[kind]
}

export function ExplorerResults({
  dataset,
  data,
  error,
  isError,
  isLoading,
  canRestart,
  detailLimitExceeded,
  onSelect,
  onNextPage,
  onRestart,
}: ExplorerResultsProps) {
  const m = useMessages()
  const resultsText = m.explorer.results
  return (
    <Card>
      <CardContent className="pt-6">
        {detailLimitExceeded ? (
          <p className="text-xs text-amber-300">{resultsText.detailLimitExceeded(String(dataset.maxDays))}</p>
        ) : isLoading ? (
          <p className="text-xs text-slate-500">{resultsText.loading}</p>
        ) : isError && error ? (
          <div>
            <p className="text-xs text-rose-300">{listErrorMessage(error.kind, resultsText)}</p>
            {canRestart && error.kind === 'cursorRejected' && (
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
