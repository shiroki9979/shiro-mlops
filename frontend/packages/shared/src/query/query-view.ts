// Shared takes TanStack Query's result structurally, so it needs no TanStack dependency. `error` is
// set exactly while TanStack's `status` is 'error', so `status` is not read.
// Errors stay `unknown`: pages classify them by shape, so a typed error would buy nothing.
export interface QueryResultLike<TData> {
  fetchStatus: 'fetching' | 'paused' | 'idle'
  data: TData | undefined
  // null while the last read has not failed.
  error: unknown
}

// A query that narrows notifyOnChangeProps must list these, or the view misses changes it depends on.
export const QUERY_VIEW_FIELDS = ['fetchStatus', 'data', 'error'] as const satisfies readonly QueryViewField[]

type QueryViewField = keyof QueryResultLike<unknown>

type QueryViewPolicy = 'data-first' | 'error-first'

const EMPTY = Symbol('empty')

interface Empty<TReason> {
  readonly [EMPTY]: TReason
}

export function emptyBecause<const TReason>(reason: TReason): Empty<TReason> {
  return { [EMPTY]: reason }
}

function isEmpty(value: unknown): value is Empty<unknown> {
  return typeof value === 'object' && value !== null && EMPTY in value
}

export type NonEmptyArray<T> = [T, ...T[]]

export function isNonEmpty<T>(items: T[]): items is NonEmptyArray<T> {
  return items.length > 0
}

// A refresh paused offline fails with no error object, so `error` is undefined then.
type Refresh = { refreshFailed: false } | { refreshFailed: true; error: unknown }

export type QueryView<TContent, TReason = never> =
  | { kind: 'loading' }
  // Typed with an absent `error` so a page can render paused and error as one failure.
  | { kind: 'paused'; error?: undefined }
  | { kind: 'disabled' }
  | { kind: 'error'; error: unknown }
  | ([TReason] extends [never] ? never : { kind: 'empty'; reason: TReason } & Refresh)
  | ({ kind: 'content'; content: TContent } & Refresh)

type ReasonOf<TSettled> = TSettled extends Empty<infer TReason> ? TReason : never

/**
 * Turns one query result into the single screen state a page renders. It lives in shared because the
 * two apps presenting the same query state differently is a bug (ADR-0014 §2.3): a failed refresh
 * over loaded data, and a read the browser holds back while offline, are decided here once.
 *
 * A page declares only two things:
 * - `policy`: `'data-first'` keeps loaded data on screen when a later read fails and sets
 *   `refreshFailed` with that read's `error`; `'error-first'` shows every failure as `error`, whatever has loaded.
 *   A read paused offline counts as a failed one: `paused` before any data, `paused` under
 *   error-first after data, `refreshFailed` under data-first.
 * - `settle` (optional): maps the data to what the page renders, or to `emptyBecause(reason)`, with as
 *   many reasons as the page needs. Only `content` and `empty` carry data, so `content` has whatever
 *   non-empty type `settle` returned (narrow arrays with `isNonEmpty`).
 *
 * Errors reach the page untouched, and a read paused offline has none (`error` is undefined); telling
 * their kinds apart is the page's job.
 *
 * @example
 * const view = toQueryView(useDatasetRows(id), {
 *   policy: 'data-first',
 *   settle: (page) => (isNonEmpty(page.items) ? { ...page, items: page.items } : emptyBecause('noRows')),
 * })
 * switch (view.kind) {
 *   case 'loading': return <Loading />
 *   case 'disabled': return <Prompt />
 *   case 'paused':
 *   case 'error': return <Failed error={view.error} />
 *   case 'empty': return <Empty reason={view.reason} stale={view.refreshFailed} />
 *   case 'content': return (
 *     <>
 *       {view.refreshFailed && <RefreshFailed error={view.error} />}
 *       <Rows items={view.content.items} />
 *     </>
 *   )
 * }
 */
export function toQueryView<TData, TSettled = TData>(
  query: QueryResultLike<TData>,
  options: { policy: QueryViewPolicy; settle?: (data: TData) => TSettled },
): QueryView<Exclude<TSettled, Empty<unknown>>, ReasonOf<TSettled>>
export function toQueryView<TData>(
  query: QueryResultLike<TData>,
  { policy, settle }: { policy: QueryViewPolicy; settle?: (data: TData) => unknown },
): QueryView<unknown, unknown> {
  const readFailed = query.error !== null || query.fetchStatus === 'paused'
  if (query.data !== undefined && (policy === 'data-first' || !readFailed)) {
    const settled = settle ? settle(query.data) : query.data
    const refresh: Refresh = readFailed
      ? { refreshFailed: true, error: query.error ?? undefined }
      : { refreshFailed: false }
    return isEmpty(settled)
      ? { kind: 'empty', reason: settled[EMPTY], ...refresh }
      : { kind: 'content', content: settled, ...refresh }
  }
  if (query.error !== null) return { kind: 'error', error: query.error }
  if (query.fetchStatus === 'paused') return { kind: 'paused' }
  if (query.fetchStatus === 'fetching') return { kind: 'loading' }
  return { kind: 'disabled' }
}
