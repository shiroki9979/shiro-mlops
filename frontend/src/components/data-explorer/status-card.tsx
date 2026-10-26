import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useLocale } from '@/i18n/locale-store'
import { useMessages } from '@/i18n/use-messages'
import { DatasetStatus } from '@/schemas/data-explorer'
import { StatusBadges } from './status-badges'
import { datasetLabel, optionalSeconds, optionalTimestamp } from './status-text'

export function DatasetStatusCard({ status }: { status: DatasetStatus }) {
  const m = useMessages()
  const locale = useLocale()
  const text = m.explorer.statusCard

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{datasetLabel(status, m)}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-xs text-slate-400">
        <StatusBadges status={status} />
        <p>{text.latestSourceAt(optionalTimestamp(status.latest_source_at, locale))}</p>
        <p>{text.latestIngestedAt(optionalTimestamp(status.latest_ingested_at, locale))}</p>
        <p>{text.ingestionAge(optionalSeconds(status.ingestion_age_seconds, locale))}</p>
        <p>{text.sourceAge(optionalSeconds(status.source_age_seconds, locale))}</p>
        {status.serving_stale != null && (
          <p>{text.servingStale(status.serving_stale ? m.common.yes : m.common.no)}</p>
        )}
        {status.missing_identifiers.length > 0 && (
          <p>{text.missingIdentifiers(status.missing_identifiers.join(', '))}</p>
        )}
        <a href={status.href} className="text-cyan-400 hover:underline">
          {text.openDetails}
        </a>
      </CardContent>
    </Card>
  )
}
