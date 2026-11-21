import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// The MSW copy must stay byte-for-byte equivalent to the exporter's fixture, which the backend unit
// tests check against the export and the Nginx smoke check serves.
const EXPORTER_FIXTURE = resolve(__dirname, '../../../../../tests/fixtures/published/latest_issued_forecast.json')
const MSW_COPY = resolve(__dirname, '../../src/mocks/latest_issued_forecast.json')

describe('published fixture copy', () => {
  it('matches the exporter fixture', () => {
    const read = (path: string) => JSON.parse(readFileSync(path, 'utf8'))
    expect(read(MSW_COPY)).toEqual(read(EXPORTER_FIXTURE))
  })
})
