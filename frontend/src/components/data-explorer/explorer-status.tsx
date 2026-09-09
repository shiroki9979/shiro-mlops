import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { DatasetStatus } from '@/schemas/data-explorer'
import type { ExplorerDatasetConfig } from './catalog'
import { StatusBadges } from './status-badges'

interface ExplorerStatusProps {
  dataset: ExplorerDatasetConfig
  status?: DatasetStatus
  auditStatus?: DatasetStatus
}

export function ExplorerStatus({ dataset, status, auditStatus }: ExplorerStatusProps) {
  if (!status) return null

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">資料集狀態</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-xs text-slate-400">
        <StatusBadges status={status} />
        <p>Ingestion age：{status.ingestion_age_seconds ?? '—'} 秒</p>
        <p>Source age：{status.source_age_seconds ?? '—'} 秒</p>
        {status.serving_stale != null && <p>Serving stale：{String(status.serving_stale)}</p>}
        {status.missing_identifiers.length > 0 && (
          <p>缺少識別：{status.missing_identifiers.join(', ')}</p>
        )}
        {auditStatus && (
          <>
            <p>
              最新 audit：{auditStatus.completeness}／擷取時間 {auditStatus.latest_source_at ?? '—'}
            </p>
            {auditStatus.missing_identifiers.length > 0 && (
              <p>Audit 缺少識別：{auditStatus.missing_identifiers.join(', ')}</p>
            )}
          </>
        )}
        {dataset.auditHref && (
          <a href={dataset.auditHref} className="text-cyan-400 hover:underline">
            {dataset.auditLabel}
          </a>
        )}
      </CardContent>
    </Card>
  )
}
