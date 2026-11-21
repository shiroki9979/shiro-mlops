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

export async function request<T>(
  endpoint: string,
  options: RequestInit = {},
  schema?: z.ZodType<T, z.ZodTypeDef, unknown>,
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
    let errorJson: unknown
    try {
      errorJson = await response.json()
      const detail = (errorJson as { detail?: unknown }).detail
      errorDetail = typeof detail === 'string' ? detail : JSON.stringify(detail ?? errorJson)
    } catch {
      // ignore
    }
    // The parsed body travels with the error so callers can read structured details.
    throw new ApiError(`API Error (${response.status}): ${errorDetail}`, response.status, errorJson)
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
