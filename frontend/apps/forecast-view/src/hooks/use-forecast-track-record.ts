import { useQuery } from '@tanstack/react-query'
import { publishedQueryKey, readPublished } from '@/lib/published'
import { ForecastTrackRecordSchema } from '@/schemas/published'

const TRACK_RECORD_FILE = 'forecast_track_record.json'
// Exported hourly locally and cached for 60 s by CloudFront, so a few minutes is fresh enough.
const BACKGROUND_REFRESH_MS = 5 * 60 * 1000

// No retries: the next background read recovers from a failure. A failed background read keeps the
// data already loaded, so the page shows its error state only when it has nothing to show.
export function useForecastTrackRecord() {
  return useQuery({
    queryKey: publishedQueryKey(TRACK_RECORD_FILE),
    queryFn: () => readPublished(TRACK_RECORD_FILE, ForecastTrackRecordSchema),
    refetchInterval: BACKGROUND_REFRESH_MS,
    retry: false,
    // Re-render on every settled read, even one whose JSON is byte-identical (structural sharing keeps
    // `data` the same object), so the stale hint is checked again against the viewer's clock.
    notifyOnChangeProps: ['data', 'isError', 'dataUpdatedAt', 'errorUpdatedAt'],
  })
}
