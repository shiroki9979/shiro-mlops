import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { DatasetStatusCard } from '@/components/data-explorer/status-card'
import { useDatasetStatus } from '@/hooks/use-data-explorer'
import { Database } from 'lucide-react'

export const dataRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/data',
  component: DataExplorerOverview,
})

function DataExplorerOverview() {
  const { data, isLoading, isError } = useDatasetStatus()

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
          <Database className="h-5 w-5 text-cyan-400" />
          營運資料檢視器 (Data Explorer)
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          查驗已入庫電力與氣象資料的可用性、新鮮度與完整度。時區：Asia/Taipei
        </p>
      </div>
      {isLoading && <p className="text-xs text-slate-500">載入資料集狀態中...</p>}
      {isError && <p className="text-xs text-rose-300">無法取得資料集狀態。</p>}
      <div className="grid gap-4 md:grid-cols-2">
        {data?.datasets.map((status) => (
          <DatasetStatusCard key={status.id} status={status} />
        ))}
      </div>
    </div>
  )
}
