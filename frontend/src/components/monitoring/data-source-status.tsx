import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatusBadges } from '@/components/data-explorer/status-badges'
import { useDatasetStatus } from '@/hooks/use-data-explorer'
import { useHealth } from '@/hooks/use-health'
import { useMessages } from '@/i18n/use-messages'
import { datasetLabel } from '@/components/data-explorer/status-text'
import { Radio } from 'lucide-react'

export function DataSourceStatus() {
  const { data: health } = useHealth()
  const { data, isLoading, isError } = useDatasetStatus()
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
        {isLoading && <p className="text-xs text-slate-500">{sourcesText.loading}</p>}
        {isError && <p className="text-xs text-rose-300">{sourcesText.error}</p>}
        {data?.datasets.map((status) => (
          <div key={status.id} className="space-y-2 rounded-lg border border-slate-800 p-3">
            <div className="flex items-center justify-between">
              <p className="text-sm text-slate-200">{datasetLabel(status, m)}</p>
              {health?.data_explorer_enabled ? (
                <a href={status.href} className="text-xs text-cyan-400 hover:underline">
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
