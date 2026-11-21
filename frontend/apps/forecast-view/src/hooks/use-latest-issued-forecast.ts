import { useQuery } from '@tanstack/react-query'
import { readPublished } from '@/lib/published'
import { LATEST_ISSUED_FORECAST_FILE, LatestIssuedForecastSchema } from '@/schemas/published'
import { useDashboardStore } from '@/store/dashboard-store'

// The key does not depend on the preset: one forecast is read once, and presets only slice it on screen.
export function useLatestIssuedForecast() {
  const { autoRefresh, refreshIntervalSec } = useDashboardStore()

  return useQuery({
    queryKey: ['published', LATEST_ISSUED_FORECAST_FILE],
    queryFn: () => readPublished(LATEST_ISSUED_FORECAST_FILE, LatestIssuedForecastSchema),
    refetchInterval: autoRefresh ? refreshIntervalSec * 1000 : false,
    // Nginx and CloudFront serve the file with max-age=60.
    staleTime: 60000,
  })
}
