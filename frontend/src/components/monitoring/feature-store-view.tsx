import { useLatestFeatures } from '@/hooks/use-latest-features'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDateTime, formatLoadMW, formatTemperature } from '@/lib/utils'
import { Database, Layers } from 'lucide-react'

export function FeatureStoreView() {
  const { data: features, isLoading, isError } = useLatestFeatures(12)

  return (
    <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-indigo-400" />
          <CardTitle className="text-base font-semibold text-slate-200">
            Feast Feature Store 實體特徵檢視 (Online / Offline Snapshot)
          </CardTitle>
        </div>
        <span className="text-xs font-mono text-slate-400 flex items-center gap-1.5">
          <Layers className="h-3.5 w-3.5 text-cyan-400" />
          FeatureView: taipower_load_stats:v1
        </span>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="py-8 text-center text-xs text-slate-500">
            從 Feature Store 讀取特徵快照中...
          </div>
        ) : isError || !features || features.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-500">
            尚無特徵快照或連線異常
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>時間戳記 (Event Timestamp)</TableHead>
                <TableHead className="text-right">負載歷史值 (MW)</TableHead>
                <TableHead className="text-right">實測氣溫 (°C)</TableHead>
                <TableHead className="text-right">相對濕度 (%)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {features.map((row, idx) => (
                <TableRow key={idx}>
                  <TableCell className="font-mono text-xs text-slate-300">
                    {formatDateTime(row.datetime)}
                  </TableCell>
                  <TableCell className="text-right font-mono font-semibold text-cyan-300 text-xs">
                    {row.load_mw ? formatLoadMW(row.load_mw) : '--'}
                  </TableCell>
                  <TableCell className="text-right font-mono text-amber-300 text-xs">
                    {row.temperature ? formatTemperature(row.temperature) : '--'}
                  </TableCell>
                  <TableCell className="text-right font-mono text-slate-300 text-xs">
                    {row.relative_humidity ? `${row.relative_humidity.toFixed(1)}%` : '--'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
