import { z } from 'zod'

// Public JSON contracts of /published/ (data-contracts §6). Unknown extra fields are stripped, so a
// field added to the export does not break deployed pages and is never shown; a missing or mistyped
// field fails the read.

const PublishedTimestampSchema = z.string().datetime({ offset: true })

// `latest_issued_forecast.json` (data contract §6.1).
export const ForecastStepSchema = z.object({
  target_hour: PublishedTimestampSchema,
  predicted_load_mw: z.number(),
})

export type ForecastStep = z.infer<typeof ForecastStepSchema>

export const LatestIssuedForecastSchema = z.object({
  issued_at: PublishedTimestampSchema.nullable(),
  steps: z.array(ForecastStepSchema),
})

export type LatestIssuedForecast = z.infer<typeof LatestIssuedForecastSchema>

export const LATEST_ISSUED_FORECAST_FILE = 'latest_issued_forecast.json'

// `forecast_track_record.json` (data contract §6.2).
const LeadTimeMetricsSchema = z.object({
  lead_time_hours: z.number().int(),
  mape: z.number().nullable(),
  mae: z.number().nullable(),
})

export const ForecastTrackRecordSchema = z.object({
  cutoff: PublishedTimestampSchema,
  accumulated_days: z.number().int().min(0).max(31),
  metrics: z
    .object({
      lead_time_curve: z.array(LeadTimeMetricsSchema),
      lead_24: LeadTimeMetricsSchema,
      lead_24_series: z.array(
        z.object({
          target_hour: PublishedTimestampSchema,
          actual_load_mw: z.number(),
          predicted_load_mw: z.number(),
        }),
      ),
    })
    .nullable(),
})

export type ForecastTrackRecord = z.infer<typeof ForecastTrackRecordSchema>
export type LeadTimeMetrics = z.infer<typeof LeadTimeMetricsSchema>

export const FORECAST_TRACK_RECORD_FILE = 'forecast_track_record.json'
