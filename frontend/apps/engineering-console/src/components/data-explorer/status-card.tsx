import { consoleHref } from '@/lib/console-href'
import { Card, CardContent, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'
import { DatasetStatus } from '@/schemas/data-explorer'
import { datasetById, isExplorerDatasetId } from './catalog'
import { DatasetSparkline } from './dataset-sparkline'
import { StatusBadges } from './status-badges'
import { DatasetStatusDetails } from './status-details'
import { datasetLabel, optionalTimestamp } from './status-text'

interface DatasetStatusCardProps {
  status: DatasetStatus
  // The home page's entry time; every card previews the 24 hours around it.
  now: Date
}

export function DatasetStatusCard({ status, now }: DatasetStatusCardProps) {
  const m = useMessages()
  const locale = useLocale()
  const statusCardText = m.explorer.statusCard

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{datasetLabel(status, m)}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-xs text-slate-400">
        <StatusBadges status={status} />
        {isExplorerDatasetId(status.id) && <DatasetSparkline dataset={datasetById(status.id)} now={now} />}
        <p>{statusCardText.latestSourceAt(optionalTimestamp(status.latest_source_at, locale))}</p>
        <p>{statusCardText.latestIngestedAt(optionalTimestamp(status.latest_ingested_at, locale))}</p>
        <DatasetStatusDetails status={status} />
        <a href={consoleHref(status.href)} className="text-cyan-400 hover:underline">
          {statusCardText.openDetails}
        </a>
      </CardContent>
    </Card>
  )
}
