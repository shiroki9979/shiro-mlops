import { z } from 'zod'
import { ApiError, InvalidResponseError, request } from '@shiro-mlops/shared/api'
import {
  HealthResponse,
  HealthResponseSchema,
  PredictionRequest,
  PredictionResponse,
  PredictionResponseSchema,
} from '@/schemas/api'
import {
  ListEnvelope,
  ListEnvelopeSchema,
  type ResolvedBucket,
  ResolvedBucketSchema,
  SeriesResponse,
  SeriesResponseSchema,
  StatusResponse,
  StatusResponseSchema,
} from '@/schemas/data-explorer'

// The API caps a list page at 200 rows (MAX_LIMIT in src/shiro_mlops/service/data_explorer/query.py);
// asking for the cap lets one day of regional snapshots fit in three pages.
const LIST_PAGE_SIZE = '200'

export type QueryParams = Record<string, string | string[] | undefined>

export type DataExplorerErrorKind =
  | 'cursorRejected'
  | 'invalidQuery'
  | 'databaseUnavailable'
  | 'invalidResponse'
  | 'other'

// Status codes per docs/reference/data-explorer.md §7 and docs/reference/rest-api.md §5.3.
const KIND_BY_STATUS: Partial<Record<number, DataExplorerErrorKind>> = {
  400: 'cursorRejected',
  422: 'invalidQuery',
  503: 'databaseUnavailable',
}

// A series 422 over the point cap names the finest bucket within it (docs/reference/rest-api.md §5.3).
const InvalidQueryBodySchema = z.object({
  detail: z.object({ suggested_bucket: ResolvedBucketSchema }),
})

export class DataExplorerError extends Error {
  constructor(
    public readonly kind: DataExplorerErrorKind,
    message: string,
    // Only an invalidQuery carries it, and only when the API named a bucket the chart can apply.
    public readonly suggestedBucket?: ResolvedBucket,
  ) {
    super(message)
    this.name = 'DataExplorerError'
  }
}

function suggestedBucketOf(body: unknown): ResolvedBucket | undefined {
  const parsed = InvalidQueryBodySchema.safeParse(body)
  return parsed.success ? parsed.data.detail.suggested_bucket : undefined
}

function toDataExplorerError(error: unknown): DataExplorerError {
  if (error instanceof ApiError) {
    const kind = KIND_BY_STATUS[error.status] ?? 'other'
    const suggestedBucket = kind === 'invalidQuery' ? suggestedBucketOf(error.data) : undefined
    return new DataExplorerError(kind, error.message, suggestedBucket)
  }
  if (error instanceof InvalidResponseError) {
    return new DataExplorerError('invalidResponse', error.message)
  }
  return new DataExplorerError('other', error instanceof Error ? error.message : String(error))
}

async function dataExplorerRequest<T>(endpoint: string, schema: z.ZodType<T, z.ZodTypeDef, unknown>): Promise<T> {
  try {
    return await request<T>(endpoint, { method: 'GET' }, schema)
  } catch (error) {
    throw toDataExplorerError(error)
  }
}

// Array values become repeated keys (`fields=a&fields=b`), which the series API reads as a list.
function toQuery(params: QueryParams): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    const values = Array.isArray(value) ? value : [value]
    values.forEach((item) => {
      if (item) search.append(key, item)
    })
  })
  const encoded = search.toString()
  return encoded ? `?${encoded}` : ''
}

export const apiClient = {
  async getHealth(): Promise<HealthResponse> {
    return request<HealthResponse>('/health', { method: 'GET' }, HealthResponseSchema)
  },

  async predict(params: PredictionRequest): Promise<PredictionResponse> {
    return request<PredictionResponse>(
      '/predict',
      {
        method: 'POST',
        body: JSON.stringify(params),
      },
      PredictionResponseSchema,
    )
  },

  async getDataStatus(): Promise<StatusResponse> {
    return request<StatusResponse>('/data/status', { method: 'GET' }, StatusResponseSchema)
  },

  async getDataList(
    path: string,
    params: Record<string, string | undefined> = {},
  ): Promise<ListEnvelope> {
    const query = toQuery({ ...params, limit: LIST_PAGE_SIZE })
    return dataExplorerRequest(`${path}${query}`, ListEnvelopeSchema)
  },

  async getDataSeries(path: string, params: QueryParams = {}): Promise<SeriesResponse> {
    return dataExplorerRequest(`${path}${toQuery(params)}`, SeriesResponseSchema)
  },
}
