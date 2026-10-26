import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useLocale } from '@/i18n/locale-store'
import { useMessages } from '@/i18n/use-messages'
import type { DatasetStatus } from '@/schemas/data-explorer'
import type { ExplorerDatasetConfig } from './catalog'
import { StatusBadges } from './status-badges'
import { optionalSeconds, optionalTimestamp } from './status-text'

interface ExplorerStatusProps {
  dataset: ExplorerDatasetConfig
  status?: DatasetStatus
  auditStatus?: DatasetStatus
}

export function ExplorerStatus({ dataset, status, auditStatus }: ExplorerStatusProps) {
  const m = useMessages()
  const locale = useLocale()
  if (!status) return null
  const cardText = m.explorer.statusCard
  const text = m.explorer.datasetStatus

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{text.title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-xs text-slate-400">
        <StatusBadges status={status} />
        <p>{cardText.ingestionAge(optionalSeconds(status.ingestion_age_seconds, locale))}</p>
        <p>{cardText.sourceAge(optionalSeconds(status.source_age_seconds, locale))}</p>
        {status.serving_stale != null && (
          <p>{cardText.servingStale(status.serving_stale ? m.common.yes : m.common.no)}</p>
        )}
        {status.missing_identifiers.length > 0 && (
          <p>{cardText.missingIdentifiers(status.missing_identifiers.join(', '))}</p>
        )}
        {auditStatus && (
          <>
            <p>
              {text.latestAudit(
                m.status.completeness[auditStatus.completeness],
                optionalTimestamp(auditStatus.latest_source_at, locale),
              )}
            </p>
            {auditStatus.missing_identifiers.length > 0 && (
              <p>{text.auditMissingIdentifiers(auditStatus.missing_identifiers.join(', '))}</p>
            )}
          </>
        )}
        {dataset.auditHref && (
          <a href={dataset.auditHref} className="text-cyan-400 hover:underline">
            {text.auditHistory}
          </a>
        )}
      </CardContent>
    </Card>
  )
}
