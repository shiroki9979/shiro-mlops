import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatusBadges } from '@/components/data-explorer/status-badges'
import { useDatasetStatus } from '@/hooks/use-data-explorer'
import { useHealth } from '@/hooks/use-health'
import { Radio } from 'lucide-react'

export function DataSourceStatus() {
  const { data: health } = useHealth()
  const { data, isLoading, isError } = useDatasetStatus()

  return (
    <Card className="border-slate-800 bg-slate-900/60">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Radio className="h-4 w-4 text-cyan-400" />
          Data Source Status
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading && <p className="text-xs text-slate-500">載入資料來源狀態中...</p>}
        {isError && <p className="text-xs text-rose-300">資料庫無法連線或狀態 API 不可用。</p>}
        {data?.datasets.map((status) => (
          <div key={status.id} className="space-y-2 rounded-lg border border-slate-800 p-3">
            <div className="flex items-center justify-between">
              <p className="text-sm text-slate-200">{status.label}</p>
              {health?.data_explorer_enabled ? (
                <a href={status.href} className="text-xs text-cyan-400 hover:underline">
                  開啟 Explorer
                </a>
              ) : (
                <span className="text-xs text-slate-500">Explorer 未啟用</span>
              )}
            </div>
            <StatusBadges status={status} />
            <p className="text-xs text-slate-500">
              empty / incomplete / stale / unavailable 分別對應無資料、不完整、過期與資料庫不可用。
            </p>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
