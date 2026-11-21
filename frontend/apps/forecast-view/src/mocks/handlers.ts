import { http, HttpResponse } from 'msw'
// A copy of the exporter's fixture tests/fixtures/published/latest_issued_forecast.json (data contract
// §6.1), kept inside frontend/ because the Docker build context is frontend/ only. The
// published-fixture-sync unit test fails when the two drift.
import latestIssuedForecast from './latest_issued_forecast.json'

export const handlers = [
  http.get('*/published/latest_issued_forecast.json', () => HttpResponse.json(latestIssuedForecast)),
]
