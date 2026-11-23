import { Button } from '@shiro-mlops/shared/ui/button'
import { Card, CardContent } from '@shiro-mlops/shared/ui/card'
import {
  emptyBecause,
  isNonEmpty,
  type NonEmptyArray,
  type QueryResultLike,
  type QueryView,
  toQueryView,
} from '@shiro-mlops/shared/query-view'
import { type Messages, useMessages } from '@/i18n/messages'
import type { DataExplorerError } from '@/lib/api-client'
import type { ListEnvelope } from '@/schemas/data-explorer'
import type { ExplorerDatasetConfig } from './catalog'
import { ExplorerGapList } from './explorer-gap-list'
import { ExplorerTable } from './explorer-table'

interface ExplorerResultsProps {
  dataset: ExplorerDatasetConfig
  list: QueryResultLike<ListEnvelope, DataExplorerError>
  canRestart: boolean
  detailLimitExceeded: boolean
  onSelect: (row: Record<string, unknown>) => void
  onNextPage: (cursor: string | undefined) => void
  onRestart: () => void
}

// A read paused offline has no error, so it shows the generic failure.
function listErrorMessage(error: DataExplorerError | undefined, resultsText: Messages['explorer']['results']): string {
  switch (error?.kind) {
    case 'cursorRejected':
      return resultsText.cursorRejected
    case 'invalidQuery':
      return resultsText.invalidFilters
    case 'databaseUnavailable':
      return resultsText.databaseUnavailable
    case 'invalidResponse':
    case 'other':
    case undefined:
      return resultsText.queryFailed
  }
}

export function ExplorerResults({
  dataset,
  list,
  canRestart,
  detailLimitExceeded,
  onSelect,
  onNextPage,
  onRestart,
}: ExplorerResultsProps) {
  const m = useMessages()
  const resultsText = m.explorer.results
  const view = toQueryView(list, {
    policy: 'data-first',
    settle: (page) => (isNonEmpty(page.items) ? { ...page, items: page.items } : emptyBecause('noRows')),
  })
  const failedRefresh = (view.kind === 'content' || view.kind === 'empty') && view.refreshFailed ? view : undefined
  const readError = view.kind === 'error' || view.kind === 'paused' ? view.error : failedRefresh?.error

  return (
    <Card>
      <CardContent className="pt-6">
        {detailLimitExceeded ? (
          <p className="text-xs text-amber-300">{resultsText.detailLimitExceeded(String(dataset.maxDays))}</p>
        ) : (
          <>
            {failedRefresh && (
              <p className="mb-4 text-xs text-rose-300">{resultsText.refreshFailed(listErrorMessage(failedRefresh.error, resultsText))}</p>
            )}
            <ResultsBody
              view={view}
              dataset={dataset}
              text={resultsText}
              nextPageText={m.common.nextPage}
              onSelect={onSelect}
              onNextPage={onNextPage}
            />
            {canRestart && readError?.kind === 'cursorRejected' && (
              <Button className="mt-4" variant="outline" onClick={onRestart}>{resultsText.backToFirstPage}</Button>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

type ResultsPage = ListEnvelope & { items: NonEmptyArray<ListEnvelope['items'][number]> }

interface ResultsBodyProps {
  view: QueryView<ResultsPage, 'noRows', DataExplorerError>
  dataset: ExplorerDatasetConfig
  text: Messages['explorer']['results']
  nextPageText: string
  onSelect: (row: Record<string, unknown>) => void
  onNextPage: (cursor: string | undefined) => void
}

function ResultsBody({ view, dataset, text, nextPageText, onSelect, onNextPage }: ResultsBodyProps) {
  switch (view.kind) {
    case 'loading':
      return <p className="text-xs text-slate-500">{text.loading}</p>
    // Only the detail limit disables the list, and the card shows its hint in place of this body.
    case 'disabled':
      return null
    case 'paused':
    case 'error':
      return <p className="text-xs text-rose-300">{listErrorMessage(view.error, text)}</p>
    case 'empty':
      return <p className="text-xs text-slate-500">{text.empty}</p>
    case 'content': {
      const page = view.content
      return (
        <>
          <ExplorerGapList datasetId={dataset.id} missingSlots={page.missing_slots} />
          <ExplorerTable columns={dataset.columns} rows={page.items} onSelect={onSelect} />
          {page.has_more && (
            <Button className="mt-4" variant="outline" onClick={() => onNextPage(page.next_cursor ?? undefined)}>
              {nextPageText}
            </Button>
          )}
        </>
      )
    }
  }
}
