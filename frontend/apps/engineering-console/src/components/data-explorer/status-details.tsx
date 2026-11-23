import { formatNumber } from '@shiro-mlops/shared/i18n/format'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'
import type { PopulatedDatasetStatus } from '@/schemas/data-explorer'

// Age, staleness and gap lines shared by the overview status card and the per-dataset status panel.
export function DatasetStatusDetails({ status }: { status: PopulatedDatasetStatus }) {
  const m = useMessages()
  const locale = useLocale()
  const statusCardText = m.explorer.statusCard

  return (
    <>
      <p>{statusCardText.ingestionAge(formatNumber(status.ingestion_age_seconds, locale))}</p>
      <p>{statusCardText.sourceAge(formatNumber(status.source_age_seconds, locale))}</p>
      {status.latest_release_stale != null && (
        <p>{statusCardText.latestReleaseStale(status.latest_release_stale ? m.common.yes : m.common.no)}</p>
      )}
      {status.missing_identifiers.length > 0 && (
        <p>{statusCardText.missingIdentifiers(status.missing_identifiers.join(', '))}</p>
      )}
    </>
  )
}
