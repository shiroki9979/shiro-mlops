import { http, HttpResponse } from 'msw'
// The exporter's own fixture (data contract §6.1), so tests read what the Nginx smoke check serves.
import latestIssuedForecast from '../../../../../tests/fixtures/published/latest_issued_forecast.json'

export const handlers = [
  http.get('*/published/latest_issued_forecast.json', () => HttpResponse.json(latestIssuedForecast)),
]
