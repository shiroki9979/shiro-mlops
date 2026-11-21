import { describe, expect, it } from 'vitest'
import { HealthResponseSchema } from '@/schemas/api'

describe('API Zod Schemas Validation', () => {
  it('validates a valid HealthResponse correctly', () => {
    const validData = {
      status: 'ok',
      version: '0.1.0',
      environment: 'production',
      model_loaded: true,
    }
    const result = HealthResponseSchema.safeParse(validData)
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.model_loaded).toBe(true)
    }
  })

  it('rejects invalid HealthResponse when fields are missing', () => {
    const invalidData = {
      status: 'ok',
      // missing version, environment, model_loaded
    }
    const result = HealthResponseSchema.safeParse(invalidData)
    expect(result.success).toBe(false)
  })
})
