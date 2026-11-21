import type { z } from 'zod'

// The one error every failed `/published/` read becomes (ADR-0015 §2.4; forecast-view-hosting §4).
// A missing file is 403 from CloudFront but 404 from local Nginx, so callers must not tell failures
// apart: the message carries nothing a viewer could be shown, and the underlying failure stays in `cause`.
export class PublishedReadError extends Error {
  constructor(fileName: string, options?: { cause?: unknown }) {
    super(`Could not read /published/${fileName}`, options)
    this.name = 'PublishedReadError'
  }
}

// Reads a precomputed Forecast View file by relative path; Cache-Control is left to Nginx and CloudFront.
// A non-2xx response, a network error, a body that is not JSON and a schema mismatch all throw
// PublishedReadError.
export async function readPublished<T>(
  fileName: string,
  schema: z.ZodType<T, z.ZodTypeDef, unknown>,
): Promise<T> {
  let body: unknown
  try {
    const response = await fetch(`/published/${fileName}`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    body = await response.json()
  } catch (cause) {
    throw new PublishedReadError(fileName, { cause })
  }
  const parsed = schema.safeParse(body)
  if (!parsed.success) throw new PublishedReadError(fileName, { cause: parsed.error })
  return parsed.data
}
