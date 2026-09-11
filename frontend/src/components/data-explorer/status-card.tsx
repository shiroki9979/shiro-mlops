import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DatasetStatus } from '@/schemas/data-explorer'
import { StatusBadges } from './status-badges'

export function DatasetStatusCard({ status }: { status: DatasetStatus }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{status.label}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-xs text-slate-400">
        <StatusBadges status={status} />
        <p>最新來源時間：{status.latest_source_at ?? '—'}</p>
        <p>最新入庫時間：{status.latest_ingested_at ?? '—'}</p>
        <p>Ingestion age：{status.ingestion_age_seconds ?? '—'} 秒</p>
        <p>Source age：{status.source_age_seconds ?? '—'} 秒</p>
        {status.serving_stale != null && <p>Serving stale：{String(status.serving_stale)}</p>}
        {status.missing_identifiers.length > 0 && (
          <p>缺少識別：{status.missing_identifiers.join(', ')}</p>
        )}
        <a href={status.href} className="text-cyan-400 hover:underline">
          開啟明細
        </a>
      </CardContent>
    </Card>
  )
}
