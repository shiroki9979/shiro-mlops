import { useLocale } from '@/i18n/locale-store'
import { useMessages } from '@/i18n/use-messages'
import type { DatasetStatus } from '@/schemas/data-explorer'
import { optionalSeconds } from './status-text'

// Age, staleness and gap lines shared by the overview status card and the per-dataset status panel.
export function DatasetStatusDetails({ status }: { status: DatasetStatus }) {
  const m = useMessages()
  const locale = useLocale()
  const statusCardText = m.explorer.statusCard

  return (
    <>
      <p>{statusCardText.ingestionAge(optionalSeconds(status.ingestion_age_seconds, locale))}</p>
      <p>{statusCardText.sourceAge(optionalSeconds(status.source_age_seconds, locale))}</p>
      {status.serving_stale != null && (
        <p>{statusCardText.servingStale(status.serving_stale ? m.common.yes : m.common.no)}</p>
      )}
      {status.missing_identifiers.length > 0 && (
        <p>{statusCardText.missingIdentifiers(status.missing_identifiers.join(', '))}</p>
      )}
    </>
  )
}
