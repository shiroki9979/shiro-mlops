import { consoleHref } from '@/lib/console-href'
import { Card, CardContent, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import { toQueryView } from '@shiro-mlops/shared/query-view'
import { StatusBadges } from '@/components/data-explorer/status-badges'
import { useDatasetStatus } from '@/hooks/use-data-explorer'
import { useHealth } from '@/hooks/use-health'
import { useMessages } from '@/i18n/messages'
import { datasetLabel } from '@/components/data-explorer/status-text'
import { Radio } from 'lucide-react'

export function DataSourceStatus() {
  const { data: health } = useHealth()
  const view = toQueryView(useDatasetStatus(), { policy: 'data-first' })
  const m = useMessages()
  const sourcesText = m.monitoring.sources

  return (
    <Card className="border-slate-800 bg-slate-900/60">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Radio className="h-4 w-4 text-cyan-400" />
          {sourcesText.title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {view.kind === 'loading' && <p className="text-xs text-slate-500">{sourcesText.loading}</p>}
        {/* The status query is never disabled; 'disabled' is listed only so every kind is handled. */}
        {(view.kind === 'error' || view.kind === 'paused' || view.kind === 'disabled') && (
          <p className="text-xs text-rose-300">{sourcesText.error}</p>
        )}
        {view.kind === 'content' && view.refreshFailed && (
          <p className="text-xs text-amber-300">{sourcesText.refreshFailed}</p>
        )}
        {view.kind === 'content' && view.content.datasets.map((status) => (
          <div key={status.id} className="space-y-2 rounded-lg border border-slate-800 p-3">
            <div className="flex items-center justify-between">
              <p className="text-sm text-slate-200">{datasetLabel(status, m)}</p>
              {health?.data_explorer_enabled ? (
                <a href={consoleHref(status.href)} className="text-xs text-cyan-400 hover:underline">
                  {sourcesText.openExplorer}
                </a>
              ) : (
                <span className="text-xs text-slate-500">{sourcesText.explorerDisabled}</span>
              )}
            </div>
            <StatusBadges status={status} />
            <p className="text-xs text-slate-500">
              {sourcesText.legend}
            </p>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
