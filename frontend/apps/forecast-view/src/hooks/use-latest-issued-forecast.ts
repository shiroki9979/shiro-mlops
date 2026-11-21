import { useQuery } from '@tanstack/react-query'
import { publishedQueryKey, readPublished } from '@/lib/published'
import { LATEST_ISSUED_FORECAST_FILE, LatestIssuedForecastSchema } from '@/schemas/published'
import { useDashboardStore } from '@/store/dashboard-store'

// The key does not depend on the preset: one forecast is read once, and presets only slice it on screen.
export function useLatestIssuedForecast() {
  const { autoRefresh, refreshIntervalSec } = useDashboardStore()

  return useQuery({
    queryKey: publishedQueryKey(LATEST_ISSUED_FORECAST_FILE),
    queryFn: () => readPublished(LATEST_ISSUED_FORECAST_FILE, LatestIssuedForecastSchema),
    refetchInterval: autoRefresh ? refreshIntervalSec * 1000 : false,
    // Matches the max-age=60 Nginx and CloudFront serve the file with; keep in sync with the
    // `/published/` Cache-Control in frontend/nginx.conf.
    staleTime: 60000,
    // One retry rides out a blip; React Query's default of 3 would hold back the neutral error for ~7s.
    retry: 1,
  })
}
