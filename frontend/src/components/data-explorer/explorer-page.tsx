import { useMemo, useState } from 'react'
import { Link, useNavigate, useRouterState } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useDatasetList, useDatasetStatus } from '@/hooks/use-data-explorer'
import {
  defaultWindow,
  exportCsv,
  formatExplorerValue,
  fromRfc3339,
  toRfc3339,
} from '@/lib/data-explorer'
import { ExplorerDatasetConfig } from './catalog'
import { StatusBadges } from './status-badges'
import { Database, Download, RefreshCw } from 'lucide-react'

function listErrorMessage(error: unknown): string {
  if (typeof error !== 'object' || error === null || !('status' in error)) {
    return '查詢失敗，請稍後再試。'
  }
  const status = error.status
  if (status === 400) return '分頁游標無效或已與目前篩選條件不相容。'
  if (status === 422) return '篩選條件無效，請確認時間範圍與欄位格式。'
  if (status === 503) return '資料庫目前無法連線，請稍後再試。'
  return '查詢失敗，請稍後再試。'
}

export function ExplorerPage({ dataset }: { dataset: ExplorerDatasetConfig }) {
  const router = useRouterState()
  const navigate = useNavigate()
  const search = router.location.search as Record<string, string | undefined>
  const windowDefaults = defaultWindow(dataset.defaultHours, dataset.lookAheadHours ?? 0)
  const start = search.start || toRfc3339(windowDefaults.start)
  const end = search.end || toRfc3339(windowDefaults.end)
  const cursor = search.cursor
  const filterValues = Object.fromEntries(dataset.filters.map((field) => [field.key, search[field.key]]))
  const params = {
    start,
    end,
    cursor,
    ...filterValues,
  }
  const statusQuery = useDatasetStatus()
  const listQuery = useDatasetList(dataset.apiPath, params)
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null)
  const datasetStatus = statusQuery.data?.datasets.find((item) => item.id === dataset.id)
  const auditStatus = dataset.auditDatasetId
    ? statusQuery.data?.datasets.find((item) => item.id === dataset.auditDatasetId)
    : undefined
  const fetchedAt = useMemo(
    () => (listQuery.dataUpdatedAt ? new Date(listQuery.dataUpdatedAt).toLocaleString('zh-TW') : '—'),
    [listQuery.dataUpdatedAt],
  )

  const updateSearch = (patch: Record<string, string | undefined>) => {
    const next: Record<string, string | undefined> = {
      ...search,
      start,
      end,
      ...filterValues,
      ...patch,
    }
    Object.keys(next).forEach((key) => {
      if (!next[key]) delete next[key]
    })
    void navigate({ to: dataset.path as never, search: next as never })
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs text-slate-500">
          <Link to="/data" className="text-cyan-400 hover:underline">
            Data Explorer
          </Link>
          <span> / {dataset.label}</span>
        </p>
        <h1 className="text-xl font-bold text-slate-100 mt-2">{dataset.label}</h1>
        <p className="text-xs text-slate-400 mt-1">{dataset.description} 時區：Asia/Taipei</p>
      </div>

      {datasetStatus && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">資料集狀態</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-xs text-slate-400">
            <StatusBadges status={datasetStatus} />
            <p>Ingestion age：{datasetStatus.ingestion_age_seconds ?? '—'} 秒</p>
            <p>Source age：{datasetStatus.source_age_seconds ?? '—'} 秒</p>
            {datasetStatus.serving_stale != null && (
              <p>Serving stale：{String(datasetStatus.serving_stale)}</p>
            )}
            {datasetStatus.missing_identifiers.length > 0 && (
              <p>缺少識別：{datasetStatus.missing_identifiers.join(', ')}</p>
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
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Database className="h-4 w-4 text-cyan-400" />
            篩選與查詢
          </CardTitle>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => listQuery.refetch()}>
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => exportCsv(`${dataset.id}.csv`, listQuery.data?.items ?? [])}
            >
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
                onChange={(event) => updateSearch({ start: toRfc3339(event.target.value), cursor: undefined })}
              />
            </label>
            <label className="text-xs text-slate-400 space-y-1">
              <span>結束時間</span>
              <input
                type="datetime-local"
                className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-slate-200"
                value={fromRfc3339(end)}
                onChange={(event) => updateSearch({ end: toRfc3339(event.target.value), cursor: undefined })}
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
                    updateSearch({ [field.key]: event.target.value || undefined, cursor: undefined })
                  }
                />
              </label>
            ))}
          </div>
          <p className="text-xs text-slate-500">最後取得時間：{fetchedAt}</p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          {listQuery.isLoading ? (
            <p className="text-xs text-slate-500">載入資料中...</p>
          ) : listQuery.isError ? (
            <p className="text-xs text-rose-300">{listErrorMessage(listQuery.error)}</p>
          ) : !listQuery.data || listQuery.data.items.length === 0 ? (
            <p className="text-xs text-slate-500">查無符合資料，查詢成功但結果為空。</p>
          ) : (
            <>
              {listQuery.data.missing_slots.length > 0 && (
                <p className="text-xs text-amber-300 mb-3">
                  查詢區間缺口：{listQuery.data.missing_slots.length} 筆
                </p>
              )}
              <Table>
                <TableHeader>
                  <TableRow>
                    {dataset.columns.map((column) => (
                      <TableHead key={column.key}>{column.label}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {listQuery.data.items.map((row, index) => (
                    <TableRow
                      key={index}
                      className="cursor-pointer"
                      onClick={() => setSelected(row)}
                    >
                      {dataset.columns.map((column) => (
                        <TableCell key={column.key} className="font-mono text-xs">
                          {formatExplorerValue(row[column.key])}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {listQuery.data.has_more && (
                <Button
                  className="mt-4"
                  variant="outline"
                  onClick={() => updateSearch({ cursor: listQuery.data?.next_cursor ?? undefined })}
                >
                  下一頁
                </Button>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {selected && (
        <div className="fixed inset-y-0 right-0 w-full max-w-md border-l border-slate-800 bg-slate-950 p-6 overflow-y-auto z-50">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-slate-100">Typed detail</h2>
            <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>
              關閉
            </Button>
          </div>
          <dl className="space-y-2 text-xs">
            {Object.entries(selected).map(([key, value]) => (
              <div key={key}>
                <dt className="text-slate-500">{key}</dt>
                <dd className="font-mono text-slate-200">{formatExplorerValue(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  )
}
