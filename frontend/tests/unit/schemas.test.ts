import { describe, expect, it } from 'vitest'
import {
  HealthResponseSchema,
  PredictionRequestSchema,
  PredictionResponseSchema,
} from '@/schemas/api'

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

  it('validates PredictionRequest default values', () => {
    const defaultData = {}
    const parsed = PredictionRequestSchema.parse(defaultData)
    expect(parsed.horizon_hours).toBe(24)
    expect(parsed).not.toHaveProperty('location')
  })

  it('validates PredictionResponse array schema', () => {
    const response = {
      status: 'success',
      horizon_hours: 2,
      subject: 'nationwide',
      predictions: [
        {
          datetime: '2026-08-25T12:00:00Z',
          predicted_load_mw: 32000.5,
          temperature: 32.1,
          relative_humidity: 65.0,
        },
        {
          datetime: '2026-08-25T13:00:00Z',
          predicted_load_mw: 32500.0,
          temperature: 33.0,
          relative_humidity: 62.5,
        },
      ],
    }
    const result = PredictionResponseSchema.safeParse(response)
    expect(result.success).toBe(true)
  })
})
