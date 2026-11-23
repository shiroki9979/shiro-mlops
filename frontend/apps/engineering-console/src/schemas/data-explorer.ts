import { z } from 'zod'

const datasetIdentity = { id: z.string(), label: z.string(), href: z.string() }

// A dataset with no ingested rows is `empty`; freshness and completeness exist only once it has rows.
export const DatasetStatusSchema = z.discriminatedUnion('kind', [
  z.object({ kind: z.literal('empty'), ...datasetIdentity, overall: z.literal('warning') }),
  z.object({
    kind: z.literal('populated'),
    ...datasetIdentity,
    freshness: z.enum(['fresh', 'warning']),
    completeness: z.enum(['complete', 'incomplete']),
    overall: z.enum(['healthy', 'warning']),
    latest_source_at: z.string(),
    latest_ingested_at: z.string(),
    ingestion_age_seconds: z.number(),
    source_age_seconds: z.number(),
    missing_identifiers: z.array(z.string()),
    latest_release_stale: z.boolean().nullable(),
  }),
])

export type DatasetStatus = z.infer<typeof DatasetStatusSchema>
export type PopulatedDatasetStatus = Extract<DatasetStatus, { kind: 'populated' }>

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

export const SeriesPointSchema = z.object({
  t: z.string(),
  v: z.number().nullable(),
})

export const SeriesSchema = z.object({
  field: z.string(),
  unit: z.string(),
  group: z.record(z.string(), z.string()).default({}),
  points: z.array(SeriesPointSchema),
})

export type Series = z.infer<typeof SeriesSchema>

// SYNC(src/shiro_mlops/service/data_explorer/series.py): Bucket and Agg; the first value of each is the API default.
export const BucketSchema = z.enum(['auto', 'raw', '1h', '1d'])
export const ResolvedBucketSchema = BucketSchema.exclude(['auto'])
export const AggSchema = z.enum(['avg', 'min', 'max'])
export const DEFAULT_BUCKET = BucketSchema.options[0]
export const DEFAULT_AGG = AggSchema.options[0]

export type Bucket = z.infer<typeof BucketSchema>
export type ResolvedBucket = z.infer<typeof ResolvedBucketSchema>
export type Agg = z.infer<typeof AggSchema>

export const SeriesResponseSchema = z.object({
  bucket: ResolvedBucketSchema,
  agg: AggSchema.nullable(),
  series: z.array(SeriesSchema),
  timezone: z.literal('Asia/Taipei').optional(),
})

export type SeriesResponse = z.infer<typeof SeriesResponseSchema>
