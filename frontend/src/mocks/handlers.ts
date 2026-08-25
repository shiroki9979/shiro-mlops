import { http, HttpResponse } from 'msw'

export function generateMockPredictions(horizon = 24, location = 'Taipei') {
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
    location,
    predictions,
  }
}

export const handlers = [
  // Health check endpoint
  http.get('*/health', () => {
    return HttpResponse.json({
      status: 'ok',
      version: '0.1.0',
      environment: 'local',
      model_loaded: true,
    })
  }),

  // Predict endpoint
  http.post('*/predict', async ({ request }) => {
    const body = (await request.json()) as {
      horizon_hours?: number
      location?: string
    }
    const horizon = body?.horizon_hours || 24
    const location = body?.location || 'Taipei'

    return HttpResponse.json(generateMockPredictions(horizon, location))
  }),

  // Latest features snapshot
  http.get('*/features/latest', () => {
    const baseTime = new Date()
    const features = []

    for (let i = 0; i < 24; i++) {
      const dt = new Date(baseTime.getTime() - i * 3600000)
      features.push({
        datetime: dt.toISOString(),
        load_mw: 29000 + Math.sin(i) * 5000,
        temperature: 28.5 - (i * 0.2),
        relative_humidity: 68.0 + (i * 0.3),
      })
    }

    return HttpResponse.json(features)
  }),
]
