import { z } from 'zod'

export const DatasetStatusSchema = z.object({
  id: z.string(),
  label: z.string(),
  availability: z.enum(['available', 'empty', 'unavailable']),
  freshness: z.enum(['fresh', 'warning', 'unknown']),
  completeness: z.enum(['complete', 'incomplete', 'unknown']),
  overall: z.enum(['healthy', 'warning', 'critical', 'unknown']),
  latest_source_at: z.string().nullable().optional(),
  latest_ingested_at: z.string().nullable().optional(),
  ingestion_age_seconds: z.number().nullable().optional(),
  source_age_seconds: z.number().nullable().optional(),
  missing_identifiers: z.array(z.string()).default([]),
  missing_slot_count: z.number().default(0),
  record_count: z.number().nullable().optional(),
  serving_stale: z.boolean().nullable().optional(),
  href: z.string(),
})

export type DatasetStatus = z.infer<typeof DatasetStatusSchema>

export const StatusResponseSchema = z.object({
  timezone: z.literal('Asia/Taipei'),
  datasets: z.array(DatasetStatusSchema),
})

export type StatusResponse = z.infer<typeof StatusResponseSchema>

export const ListEnvelopeSchema = z.object({
  items: z.array(z.record(z.string(), z.unknown())),
  next_cursor: z.string().nullable(),
  has_more: z.boolean(),
  missing_slots: z.array(z.string()).default([]),
  timezone: z.literal('Asia/Taipei').optional(),
})

export type ListEnvelope = z.infer<typeof ListEnvelopeSchema>
