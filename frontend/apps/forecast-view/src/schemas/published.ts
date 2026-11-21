import { z } from 'zod'

// `latest_issued_forecast.json` (data contract §6.1). Fields beyond these are dropped, never shown.
export const ForecastStepSchema = z.object({
  target_hour: z.string().datetime({ offset: true }),
  predicted_load_mw: z.number(),
})

export type ForecastStep = z.infer<typeof ForecastStepSchema>

export const LatestIssuedForecastSchema = z.object({
  issued_at: z.string().datetime({ offset: true }).nullable(),
  steps: z.array(ForecastStepSchema),
})

export type LatestIssuedForecast = z.infer<typeof LatestIssuedForecastSchema>

export const LATEST_ISSUED_FORECAST_FILE = 'latest_issued_forecast.json'
