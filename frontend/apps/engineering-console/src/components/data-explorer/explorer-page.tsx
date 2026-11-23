import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useDatasetStatus, useRefetchDatasetSeries } from '@/hooks/use-data-explorer'
import { EMPTY_VALUE, formatTimestamp } from '@shiro-mlops/shared/i18n/format'
import { useLocale } from '@shiro-mlops/shared/i18n/locale-store'
import { useMessages } from '@/i18n/messages'
import type { ExplorerDatasetConfig } from './catalog'
import { ExplorerChartCard } from './explorer-chart-card'
import { ExplorerDetail } from './explorer-detail'
import { ExplorerFilters } from './explorer-filters'
import { ExplorerResults } from './explorer-results'
import { ExplorerStatus } from './explorer-status'
import { useExplorerQuery } from './use-explorer-query'

export function ExplorerPage({ dataset }: { dataset: ExplorerDatasetConfig }) {
  const explorer = useExplorerQuery(dataset)
  const { list, series, state } = explorer
  const statusQuery = useDatasetStatus()
  const refetchSeries = useRefetchDatasetSeries()
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null)
  const datasetStatus = statusQuery.data?.datasets.find((item) => item.id === dataset.id)
  const auditStatus = dataset.auditDatasetId
    ? statusQuery.data?.datasets.find((item) => item.id === dataset.auditDatasetId)
    : undefined
  const m = useMessages()
  const locale = useLocale()
  const datasetText = m.explorer.datasets[dataset.id]
  const fetchedAt = list.dataUpdatedAt ? formatTimestamp(list.dataUpdatedAt, locale) : EMPTY_VALUE

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs text-slate-500">
          <Link to="/data" className="text-cyan-400 hover:underline">
            {m.explorer.title}
          </Link>
          <span> / {datasetText.label}</span>
        </p>
        <h1 className="text-xl font-bold text-slate-100 mt-2">{datasetText.label}</h1>
        <p className="text-xs text-slate-400 mt-1">
          {datasetText.description} {m.explorer.timeZoneNote}
        </p>
      </div>

      <ExplorerStatus dataset={dataset} status={datasetStatus} auditStatus={auditStatus} />
      <ExplorerFilters
        dataset={dataset}
        start={state.window.start}
        end={state.window.end}
        filterValues={state.filters}
        fetchedAt={fetchedAt}
        items={list.data?.items ?? []}
        csvDisabled={state.rows.kind === 'overDetailLimit'}
        onRefresh={() => {
          explorer.refetchList()
          void statusQuery.refetch()
          if (dataset.chart) void refetchSeries(dataset.chart.seriesApiPath)
        }}
        onStartChange={explorer.setStart}
        onEndChange={explorer.setEnd}
        onWindowChange={explorer.setWindow}
        onFilterChange={explorer.setFilter}
      />
      {dataset.chart && state.chart && series && (
        <ExplorerChartCard
          dataset={dataset}
          chart={dataset.chart}
          settings={state.chart}
          series={series}
          onChartChange={explorer.setChart}
          onWindowChange={explorer.setWindow}
        />
      )}
      <ExplorerResults
        dataset={dataset}
        data={list.data}
        error={list.error}
        isError={list.isError}
        isLoading={list.isLoading}
        rows={state.rows}
        onSelect={setSelected}
        onNextPage={explorer.goToNextPage}
        onRestart={explorer.restartFromFirstPage}
      />
      <ExplorerDetail selected={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
