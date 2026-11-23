import { describe, expect, it } from 'vitest'
import { emptyBecause, isNonEmpty, toQueryView } from '../src/query/query-view'

interface Listing {
  published: boolean
  rows: number[]
}

// Two ways to be empty, as a page might declare them.
function settleListing(listing: Listing) {
  if (!listing.published) return emptyBecause('notPublished')
  return isNonEmpty(listing.rows) ? { firstRow: listing.rows[0], rows: listing.rows } : emptyBecause('noRows')
}

describe('toQueryView before any data has loaded', () => {
  it('is loading while the first read is in flight', () => {
    const query = { status: 'pending', fetchStatus: 'fetching', data: undefined, error: null } as const

    expect(toQueryView(query, { policy: 'data-first' })).toEqual({ kind: 'loading' })
  })

  it('is paused when the browser is offline and the first request was never sent', () => {
    const query = { status: 'pending', fetchStatus: 'paused', data: undefined, error: null } as const

    expect(toQueryView(query, { policy: 'data-first' })).toEqual({ kind: 'paused' })
  })

  it('is disabled when the query is not enabled', () => {
    const query = { status: 'pending', fetchStatus: 'idle', data: undefined, error: null } as const

    expect(toQueryView(query, { policy: 'data-first' })).toEqual({ kind: 'disabled' })
  })
})

describe('toQueryView after a read settles', () => {
  it.each(['data-first', 'error-first'] as const)('shows a %s page the data a successful read returned', (policy) => {
    const query = { status: 'success', fetchStatus: 'idle', data: { rows: [1, 2] }, error: null } as const

    expect(toQueryView(query, { policy })).toEqual({
      kind: 'content',
      content: { rows: [1, 2] },
      refreshFailed: false,
    })
  })

  it.each(['data-first', 'error-first'] as const)('keeps a %s page on its data while a later read is in flight', (policy) => {
    const query = { status: 'success', fetchStatus: 'fetching', data: { rows: [1, 2] }, error: null } as const

    expect(toQueryView(query, { policy })).toEqual({
      kind: 'content',
      content: { rows: [1, 2] },
      refreshFailed: false,
    })
  })

  it.each(['data-first', 'error-first'] as const)(
    'hands a %s page the failure, untouched, when nothing has loaded',
    (policy) => {
      const error = new Error('403')
      const query = { status: 'error', fetchStatus: 'idle', data: undefined, error } as const

      const view = toQueryView(query, { policy })

      expect(view).toEqual({ kind: 'error', error })
      expect(view.kind === 'error' && view.error).toBe(error)
    },
  )
})

describe('toQueryView when a later read fails over loaded data', () => {
  const error = new Error('503')
  const refetchFailed = { status: 'error', fetchStatus: 'idle', data: { rows: [1, 2] }, error } as const

  it('keeps a data-first page on its data and flags the failed refresh', () => {
    expect(toQueryView(refetchFailed, { policy: 'data-first' })).toEqual({
      kind: 'content',
      content: { rows: [1, 2] },
      refreshFailed: true,
    })
  })

  it('turns an error-first page to the failure despite the data', () => {
    expect(toQueryView(refetchFailed, { policy: 'error-first' })).toEqual({ kind: 'error', error })
  })
})

// A refetch the browser holds back while offline counts as that page's failed read (#290, decision B).
describe('toQueryView when a later read is paused offline over loaded data', () => {
  const refetchPaused = { status: 'success', fetchStatus: 'paused', data: { rows: [1, 2] }, error: null } as const

  it('keeps a data-first page on its data and flags the refresh as failed', () => {
    expect(toQueryView(refetchPaused, { policy: 'data-first' })).toEqual({
      kind: 'content',
      content: { rows: [1, 2] },
      refreshFailed: true,
    })
  })

  it('turns an error-first page to paused despite the data', () => {
    expect(toQueryView(refetchPaused, { policy: 'error-first' })).toEqual({ kind: 'paused' })
  })
})

describe('toQueryView with the page judging what counts as empty', () => {
  function succeeded(listing: Listing) {
    return { status: 'success', fetchStatus: 'idle', data: listing, error: null } as const
  }

  it.each([
    ['notPublished', { published: false, rows: [1] }],
    ['noRows', { published: true, rows: [] }],
  ] as const)('is empty for the reason %s the page gave', (reason, listing) => {
    const view = toQueryView(succeeded({ ...listing, rows: [...listing.rows] }), {
      policy: 'data-first',
      settle: settleListing,
    })

    expect(view).toEqual({ kind: 'empty', reason, refreshFailed: false })
  })

  it('hands the page the content its judgement returned for data that is not empty', () => {
    const view = toQueryView(succeeded({ published: true, rows: [7, 8] }), {
      policy: 'data-first',
      settle: settleListing,
    })

    expect(view).toEqual({ kind: 'content', content: { firstRow: 7, rows: [7, 8] }, refreshFailed: false })
  })

  it('keeps a data-first page on its empty state and flags the failed refresh', () => {
    const listing: Listing = { published: true, rows: [] }
    const query = { status: 'error', fetchStatus: 'idle', data: listing, error: new Error('503') } as const

    const view = toQueryView(query, { policy: 'data-first', settle: settleListing })

    expect(view).toEqual({ kind: 'empty', reason: 'noRows', refreshFailed: true })
  })
})
