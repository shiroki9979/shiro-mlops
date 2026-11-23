import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/server'
import { apiClient, type DataExplorerError } from '@/lib/api-client'

const LIST_PATH = '/data/power/load'
const SERIES_PATH = '/data/power/load/series'

async function failureOf(call: Promise<unknown>): Promise<unknown> {
  try {
    await call
  } catch (error) {
    return error
  }
  throw new Error('expected the request to fail')
}

describe.each([
  { call: 'list', path: LIST_PATH, read: () => apiClient.getDataList(LIST_PATH) },
  { call: 'series', path: SERIES_PATH, read: () => apiClient.getDataSeries(SERIES_PATH) },
])('Data Explorer $call errors', ({ path, read }) => {
  it.each([
    [400, 'cursorRejected'],
    [422, 'invalidQuery'],
    [503, 'databaseUnavailable'],
    [500, 'other'],
    [404, 'other'],
  ])('names HTTP %s as %s and keeps the API error message', async (status, kind) => {
    server.use(http.get(`*${path}`, () => HttpResponse.json({ detail: 'request failed' }, { status })))

    const error = await failureOf(read())

    expect(error).toMatchObject({ kind, message: `API Error (${status}): request failed` })
  })

  it('names a 2xx body that breaks the schema as invalidResponse, without a status', async () => {
    server.use(http.get(`*${path}`, () => HttpResponse.json({ timezone: 'Asia/Taipei', items: 'not rows', series: 'not series' })))

    const error = await failureOf(read())

    expect(error).toMatchObject({ kind: 'invalidResponse' })
    expect((error as { status?: number }).status).toBeUndefined()
  })

  it('names a request that never reached the API as other', async () => {
    server.use(http.get(`*${path}`, () => HttpResponse.error()))

    const error = await failureOf(read())

    expect(error).toMatchObject({ kind: 'other' })
  })
})

describe('Data Explorer invalidQuery suggested bucket', () => {
  it.each([
    ['a resolved bucket', { message: 'too many points', suggested_bucket: '1d' }, '1d'],
    ['null', { message: 'too many points', suggested_bucket: null }, undefined],
    ['auto, which is not a resolved bucket', { message: 'too many points', suggested_bucket: 'auto' }, undefined],
    ['an unknown bucket', { message: 'too many points', suggested_bucket: '1w' }, undefined],
    ['missing', 'Unknown query parameter: bucket', undefined],
  ])('reads a 422 suggested_bucket that is %s', async (_case, detail, suggestedBucket) => {
    server.use(http.get(`*${SERIES_PATH}`, () => HttpResponse.json({ detail }, { status: 422 })))

    const error = await failureOf(apiClient.getDataSeries(SERIES_PATH))

    expect(error).toMatchObject({ kind: 'invalidQuery' })
    expect((error as DataExplorerError).suggestedBucket).toBe(suggestedBucket)
  })

  it('leaves the suggested bucket empty on kinds other than invalidQuery', async () => {
    server.use(http.get(`*${SERIES_PATH}`, () => HttpResponse.json({ detail: { suggested_bucket: '1d' } }, { status: 503 })))

    const error = await failureOf(apiClient.getDataSeries(SERIES_PATH))

    expect(error).toMatchObject({ kind: 'databaseUnavailable' })
    expect((error as DataExplorerError).suggestedBucket).toBeUndefined()
  })
})
