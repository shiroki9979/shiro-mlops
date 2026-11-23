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
import type { ListEnvelope } from '@/schemas/data-explorer'
import type { ExplorerDatasetConfig } from './catalog'
import { ExplorerGapList } from './explorer-gap-list'
import { ExplorerTable } from './explorer-table'

interface ExplorerResultsProps {
  dataset: ExplorerDatasetConfig
  list: QueryResultLike<ListEnvelope>
  canRestart: boolean
  detailLimitExceeded: boolean
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
  const refreshFailed = (view.kind === 'content' || view.kind === 'empty') && view.refreshFailed
  const readFailed = view.kind === 'error' || view.kind === 'paused' || refreshFailed
  // Over kept rows the view carries no error, so the notice classifies the query's own; paused has none.
  const failure = view.kind === 'error' ? view.error : list.error

  return (
    <Card>
      <CardContent className="pt-6">
        {detailLimitExceeded ? (
          <p className="text-xs text-amber-300">{resultsText.detailLimitExceeded(String(dataset.maxDays))}</p>
        ) : (
          <>
            {refreshFailed && (
              <p className="mb-4 text-xs text-rose-300">{resultsText.refreshFailed(listErrorMessage(failure, resultsText))}</p>
            )}
            <ResultsBody
              view={view}
              dataset={dataset}
              text={resultsText}
              nextPageText={m.common.nextPage}
              onSelect={onSelect}
              onNextPage={onNextPage}
            />
            {canRestart && readFailed && isCursorRejected(failure) && (
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
  view: QueryView<ResultsPage, 'noRows'>
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
      return <p className="text-xs text-rose-300">{listErrorMessage(view.kind === 'error' ? view.error : undefined, text)}</p>
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
