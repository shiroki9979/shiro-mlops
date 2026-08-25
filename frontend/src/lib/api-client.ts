import {
  FeatureSnapshot,
  FeatureSnapshotSchema,
  HealthResponse,
  HealthResponseSchema,
  PredictionRequest,
  PredictionResponse,
  PredictionResponseSchema,
} from '@/schemas/api'
import { z } from 'zod'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
    public data?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(
  endpoint: string,
  options: RequestInit = {},
  schema?: z.ZodType<T>,
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`
  const headers = new Headers(options.headers)

  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(url, {
    ...options,
    headers,
  })

  if (!response.ok) {
    let errorDetail = response.statusText
    try {
      const errorJson = await response.json()
      errorDetail = errorJson.detail || JSON.stringify(errorJson)
    } catch {
      // ignore
    }
    throw new ApiError(`API Error (${response.status}): ${errorDetail}`, response.status)
  }

  const json = await response.json()

  if (schema) {
    const parseResult = schema.safeParse(json)
    if (!parseResult.success) {
      console.error('Schema validation failed:', parseResult.error)
      throw new ApiError(`Invalid API response format: ${parseResult.error.message}`, response.status, json)
    }
    return parseResult.data
  }

  return json as T
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

  async getLatestFeatures(limit = 24): Promise<FeatureSnapshot[]> {
    return request<FeatureSnapshot[]>(
      `/features/latest?limit=${limit}`,
      { method: 'GET' },
      z.array(FeatureSnapshotSchema),
    )
  },
}
