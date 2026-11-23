import { Button } from '@shiro-mlops/shared/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import { exportCsv, fromRfc3339, toRfc3339 } from '@/lib/data-explorer'
import { Database, Download, RefreshCw } from 'lucide-react'
import { useMessages } from '@/i18n/messages'
import type { ExplorerWindow } from '@/lib/explorer-window'
import type { ExplorerDatasetConfig, ExplorerFieldKey } from './catalog'
import type { ExplorerFilterValue, ExplorerFilterValues } from './explorer-query-state'
import { ExplorerFilterField } from './explorer-filter-field'
import { ExplorerWindowNav } from './explorer-window-nav'

interface ExplorerFiltersProps {
  dataset: ExplorerDatasetConfig
  start: string
  end: string
  filterValues: ExplorerFilterValues
  fetchedAt: string
  items: Record<string, unknown>[]
  csvDisabled: boolean
  onRefresh: () => void
  onStartChange: (value: string) => void
  onEndChange: (value: string) => void
  onWindowChange: (window: ExplorerWindow) => void
  onFilterChange: (key: ExplorerFieldKey, value: ExplorerFilterValue | undefined) => void
}

export function ExplorerFilters({
  dataset,
  start,
  end,
  filterValues,
  fetchedAt,
  items,
  csvDisabled,
  onRefresh,
  onStartChange,
  onEndChange,
  onWindowChange,
  onFilterChange,
}: ExplorerFiltersProps) {
  const m = useMessages()
  const filtersText = m.explorer.filters
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Database className="h-4 w-4 text-cyan-400" />
          {filtersText.title}
        </CardTitle>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={onRefresh}>
            <RefreshCw className="h-3.5 w-3.5" />
            {m.common.refresh}
          </Button>
          <Button variant="outline" size="sm" disabled={csvDisabled} onClick={() => exportCsv(`${dataset.id}.csv`, items)}>
            <Download className="h-3.5 w-3.5" />
            {m.common.exportCsv}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <ExplorerWindowNav dataset={dataset} window={{ start, end }} onWindowChange={onWindowChange} />
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <label className="text-xs text-slate-400 space-y-1">
            <span>{filtersText.start}</span>
            <input
              type="datetime-local"
              className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-slate-200"
              value={fromRfc3339(start)}
              onChange={(event) => onStartChange(toRfc3339(event.target.value))}
            />
          </label>
          <label className="text-xs text-slate-400 space-y-1">
            <span>{filtersText.end}</span>
            <input
              type="datetime-local"
              className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-slate-200"
              value={fromRfc3339(end)}
              onChange={(event) => onEndChange(toRfc3339(event.target.value))}
            />
          </label>
          {dataset.filters.map((field) => (
            <ExplorerFilterField
              key={field.key}
              field={field}
              value={filterValues[field.key]}
              onChange={(value) => onFilterChange(field.key, value)}
            />
          ))}
        </div>
        <p className="text-xs text-slate-500">{filtersText.lastFetched(fetchedAt)}</p>
      </CardContent>
    </Card>
  )
}
