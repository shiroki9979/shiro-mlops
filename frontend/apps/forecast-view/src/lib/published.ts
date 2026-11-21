import type { z } from 'zod'

// The Forecast View reads precomputed JSON from its own origin (local Nginx or CloudFront), never
// through the shared API client: the cloud has no API origin (ADR-0015).
const PUBLISHED_PATH = '/published'

// Every way a read can fail (non-2xx, network error, unparsable body, contract mismatch) is this one
// error, with no status code to branch on: S3 answers 403 for a missing object, so a status must
// never decide what the page shows (forecast-view-hosting §4).
export class PublishedReadError extends Error {
  constructor(fileName: string, options?: ErrorOptions) {
    super(`Unable to read ${PUBLISHED_PATH}/${fileName}`, options)
    this.name = 'PublishedReadError'
  }
}

export const publishedQueryKey = (fileName: string) => ['published', fileName] as const

export async function readPublished<T>(
  fileName: string,
  schema: z.ZodType<T, z.ZodTypeDef, unknown>,
): Promise<T> {
  try {
    const response = await fetch(`${PUBLISHED_PATH}/${fileName}`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    return schema.parse(await response.json())
  } catch (cause) {
    throw new PublishedReadError(fileName, { cause })
  }
}
