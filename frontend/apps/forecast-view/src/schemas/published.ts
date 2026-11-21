import { z } from 'zod'

// Public JSON contracts of /published/ (data-contracts §6). Unknown extra fields are stripped, so a
// field added to the export does not break deployed pages; a missing or mistyped field fails the read.

const PublishedTimestampSchema = z.string().datetime({ offset: true })

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
