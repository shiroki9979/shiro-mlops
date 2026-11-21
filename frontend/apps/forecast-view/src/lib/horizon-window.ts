import type { ForecastStep } from '@/schemas/published'

export const HOURLY_PRESETS = [24, 48, 72] as const
export const WEEK_HOURS = 168

const HOUR_MS = 3_600_000

// A preset of H hours keeps the steps whose lead time is at most H. Lead time counts from the forecast
// time and rounds a partial hour up, so "lead time ≤ H" is "target hour − forecast time ≤ H hours".
// The week preset keeps every step. The viewer's clock is never read, so everyone who opens one
// forecast gets the same rows for the same preset.
export function stepsWithinHorizon(issuedAt: string, steps: ForecastStep[], horizonHours: number): ForecastStep[] {
  if (horizonHours >= WEEK_HOURS) return steps
  const issuedAtMs = Date.parse(issuedAt)
  const limitMs = horizonHours * HOUR_MS
  return steps.filter((step) => Date.parse(step.target_hour) - issuedAtMs <= limitMs)
}
