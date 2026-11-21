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
  StatusResponse,
  StatusResponseSchema,
} from '@/schemas/data-explorer'

function toQuery(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value) search.set(key, value)
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
    return request<ListEnvelope>(`${path}${toQuery(params)}`, { method: 'GET' }, ListEnvelopeSchema)
  },
}
