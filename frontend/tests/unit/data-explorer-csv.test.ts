import { afterEach, expect, it, vi } from 'vitest'
import { exportCsv } from '@/lib/data-explorer'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('exports quotes, commas, line breaks, arrays, zero and null as intact CSV cells', async () => {
  const createObjectURL = vi.fn<(blob: Blob) => string>().mockReturnValue('blob:test-csv')
  vi.stubGlobal('URL', { createObjectURL, revokeObjectURL: vi.fn() })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

  exportCsv('units.csv', [{
    remark: 'Unit "A",\nmaintenance',
    missing_station_ids: ['466920', '467490'],
    load_mw: 0,
    optional: null,
  }])

  const blob = createObjectURL.mock.calls[0][0]
  const content = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsText(blob)
  })
  expect(content).toBe(
    '"remark","missing_station_ids","load_mw","optional"\r\n' +
    '"Unit ""A"",\nmaintenance","[""466920"",""467490""]","0",""',
  )
})
