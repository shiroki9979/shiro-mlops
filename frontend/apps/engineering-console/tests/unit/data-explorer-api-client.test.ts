import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/server'
import { apiClient } from '@/lib/api-client'

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
