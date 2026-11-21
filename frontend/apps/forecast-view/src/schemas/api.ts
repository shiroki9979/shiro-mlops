import { z } from 'zod'

export const PredictionItemSchema = z.object({
  datetime: z.string(),
  predicted_load_mw: z.number(),
  temperature: z.number(),
  relative_humidity: z.number(),
})

export type PredictionItem = z.infer<typeof PredictionItemSchema>

export const PredictionRequestSchema = z.object({
  horizon_hours: z.number().int().min(1).max(168).default(24),
})

export type PredictionRequest = z.infer<typeof PredictionRequestSchema>

export const PredictionResponseSchema = z.object({
  status: z.string(),
  horizon_hours: z.number().int(),
  subject: z.string(),
  predictions: z.array(PredictionItemSchema),
})

export type PredictionResponse = z.infer<typeof PredictionResponseSchema>
