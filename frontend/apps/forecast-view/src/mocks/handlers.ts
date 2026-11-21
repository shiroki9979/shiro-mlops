import { http, HttpResponse } from 'msw'

export function generateMockPredictions(horizon = 24) {
  const baseTime = new Date()
  baseTime.setMinutes(0, 0, 0)
  const predictions = []

  for (let i = 1; i <= horizon; i++) {
    const dt = new Date(baseTime.getTime() + i * 3600000)
    const hour = dt.getHours()
    const cycle = Math.sin(((hour - 6) / 24) * 2 * Math.PI)
    const load = 28500 + cycle * 7200 + (i * 20)
    const temp = 26 + cycle * 6 + (Math.random() * 0.5)
    const humidity = 70 - cycle * 15

    predictions.push({
      datetime: dt.toISOString(),
      predicted_load_mw: parseFloat(load.toFixed(1)),
      temperature: parseFloat(temp.toFixed(1)),
      relative_humidity: parseFloat(humidity.toFixed(1)),
    })
  }

  return {
    status: 'success',
    horizon_hours: horizon,
    subject: 'nationwide',
    predictions,
  }
}

export const handlers = [
  http.post('*/predict', async ({ request }) => {
    const body = (await request.json()) as {
      horizon_hours?: number
    }
    const horizon = body?.horizon_hours || 24
    return HttpResponse.json(generateMockPredictions(horizon))
  }),
]
