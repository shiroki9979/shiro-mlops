import { consoleHref } from '@/lib/console-href'
import { Card, CardContent, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'
import type { DatasetStatus } from '@/schemas/data-explorer'
import type { ExplorerDatasetConfig } from './catalog'
import { StatusBadges } from './status-badges'
import { DatasetStatusDetails } from './status-details'
import { optionalTimestamp, translateCompleteness } from './status-text'

interface ExplorerStatusProps {
  dataset: ExplorerDatasetConfig
  status?: DatasetStatus
  auditStatus?: DatasetStatus
}

export function ExplorerStatus({ dataset, status, auditStatus }: ExplorerStatusProps) {
  const m = useMessages()
  const locale = useLocale()
  if (!status) return null
  const datasetStatusText = m.explorer.datasetStatus

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{datasetStatusText.title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-xs text-slate-400">
        <StatusBadges status={status} />
        <DatasetStatusDetails status={status} />
        {auditStatus && (
          <>
            <p>
              {datasetStatusText.latestAudit(
                translateCompleteness(auditStatus.completeness, m),
                optionalTimestamp(auditStatus.latest_source_at, locale),
              )}
            </p>
            {auditStatus.missing_identifiers.length > 0 && (
              <p>{datasetStatusText.auditMissingIdentifiers(auditStatus.missing_identifiers.join(', '))}</p>
            )}
          </>
        )}
        {dataset.auditHref && (
          <a href={consoleHref(dataset.auditHref)} className="text-cyan-400 hover:underline">
            {datasetStatusText.auditHistory}
          </a>
        )}
      </CardContent>
    </Card>
  )
}
