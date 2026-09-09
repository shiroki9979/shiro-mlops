import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { exportCsv, fromRfc3339, toRfc3339 } from '@/lib/data-explorer'
import { Database, Download, RefreshCw } from 'lucide-react'
import type { ExplorerDatasetConfig } from './catalog'

interface ExplorerFiltersProps {
  dataset: ExplorerDatasetConfig
  start: string
  end: string
  filterValues: Record<string, string | undefined>
  fetchedAt: string
  items: Record<string, unknown>[]
  onRefresh: () => void
  onSearchChange: (patch: Record<string, string | undefined>) => void
}

export function ExplorerFilters({
  dataset,
  start,
  end,
  filterValues,
  fetchedAt,
  items,
  onRefresh,
  onSearchChange,
}: ExplorerFiltersProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Database className="h-4 w-4 text-cyan-400" />
          篩選與查詢
        </CardTitle>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={onRefresh}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <Button variant="outline" size="sm" onClick={() => exportCsv(`${dataset.id}.csv`, items)}>
            <Download className="h-3.5 w-3.5" />
            匯出 CSV
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <label className="text-xs text-slate-400 space-y-1">
            <span>開始時間</span>
            <input
              type="datetime-local"
              className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-slate-200"
              value={fromRfc3339(start)}
              onChange={(event) =>
                onSearchChange({ start: toRfc3339(event.target.value), cursor: undefined })
              }
            />
          </label>
          <label className="text-xs text-slate-400 space-y-1">
            <span>結束時間</span>
            <input
              type="datetime-local"
              className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-slate-200"
              value={fromRfc3339(end)}
              onChange={(event) =>
                onSearchChange({ end: toRfc3339(event.target.value), cursor: undefined })
              }
            />
          </label>
          {dataset.filters.map((field) => (
            <label key={field.key} className="text-xs text-slate-400 space-y-1">
              <span>{field.label}</span>
              <input
                className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-slate-200"
                placeholder={field.placeholder}
                value={filterValues[field.key] ?? ''}
                onChange={(event) =>
                  onSearchChange({ [field.key]: event.target.value || undefined, cursor: undefined })
                }
              />
            </label>
          ))}
        </div>
        <p className="text-xs text-slate-500">最後取得時間：{fetchedAt}</p>
      </CardContent>
    </Card>
  )
}
