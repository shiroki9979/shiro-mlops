import { useMemo, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useDatasetList, useDatasetStatus } from '@/hooks/use-data-explorer'
import type { ExplorerDatasetConfig } from './catalog'
import { ExplorerDetail } from './explorer-detail'
import { ExplorerFilters } from './explorer-filters'
import { ExplorerResults } from './explorer-results'
import { ExplorerStatus } from './explorer-status'
import { useExplorerSearch } from './use-explorer-search'

export function ExplorerPage({ dataset }: { dataset: ExplorerDatasetConfig }) {
  const { start, end, filterValues, params, updateSearch } = useExplorerSearch(dataset)
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

      <ExplorerStatus dataset={dataset} status={datasetStatus} auditStatus={auditStatus} />
      <ExplorerFilters
        dataset={dataset}
        start={start}
        end={end}
        filterValues={filterValues}
        fetchedAt={fetchedAt}
        items={listQuery.data?.items ?? []}
        onRefresh={() => {
          void listQuery.refetch()
          void statusQuery.refetch()
        }}
        onSearchChange={updateSearch}
      />
      <ExplorerResults
        dataset={dataset}
        data={listQuery.data}
        error={listQuery.error}
        isError={listQuery.isError}
        isLoading={listQuery.isLoading}
        onSelect={setSelected}
        onNextPage={(cursor) => updateSearch({ cursor })}
      />
      <ExplorerDetail selected={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
