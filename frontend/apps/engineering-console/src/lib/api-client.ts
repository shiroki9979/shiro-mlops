import { request } from '@shiro-mlops/shared/api'
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
  SeriesResponse,
  SeriesResponseSchema,
  StatusResponse,
  StatusResponseSchema,
} from '@/schemas/data-explorer'

// The API caps a list page at 200 rows (MAX_LIMIT in src/shiro_mlops/service/data_explorer/query.py);
// asking for the cap lets one day of regional snapshots fit in three pages.
const LIST_PAGE_SIZE = '200'

export type QueryParams = Record<string, string | string[] | undefined>

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
    return request<ListEnvelope>(`${path}${query}`, { method: 'GET' }, ListEnvelopeSchema)
  },

  async getDataSeries(path: string, params: QueryParams = {}): Promise<SeriesResponse> {
    return request<SeriesResponse>(`${path}${toQuery(params)}`, { method: 'GET' }, SeriesResponseSchema)
  },
}
