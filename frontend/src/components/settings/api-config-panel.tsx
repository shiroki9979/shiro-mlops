import { useState } from 'react'
import { apiClient } from '@/lib/api-client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { CheckCircle2, Play, RefreshCw, Server, XCircle } from 'lucide-react'

export function ApiConfigPanel() {
  const [testHorizon, setTestHorizon] = useState(24)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [isSuccess, setIsSuccess] = useState<boolean | null>(null)

  const handleTestInference = async () => {
    setLoading(true)
    setResult(null)
    setIsSuccess(null)
    try {
      const response = await apiClient.predict({
        horizon_hours: testHorizon,
      })
      setIsSuccess(true)
      setResult(JSON.stringify(response, null, 2))
    } catch (err: unknown) {
      setIsSuccess(false)
      const errorMsg = err instanceof Error ? err.message : String(err)
      setResult(`推論執行錯誤: ${errorMsg}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      {/* Backend Connection Info */}
      <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Server className="h-5 w-5 text-cyan-400" />
            <CardTitle className="text-base font-semibold text-slate-200">
              後端推論伺服器設定 (FastAPI Connection)
            </CardTitle>
          </div>
          <CardDescription>
            設定推論服務端點與資料快取降級策略
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-xs">
          <div className="space-y-1.5">
            <label className="text-slate-400 font-medium">API Base Endpoint</label>
            <input
              type="text"
              readOnly
              value={import.meta.env.VITE_API_BASE_URL || '/api (same-origin proxy)'}
              className="w-full bg-slate-950/80 border border-slate-800 rounded-lg px-3 py-2 text-slate-300 font-mono"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-slate-400 font-medium">資料重試與指數退避 (Resiliency)</label>
            <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 space-y-2">
              <div className="flex justify-between">
                <span className="text-slate-400">重試次數 (Max Retries)</span>
                <span className="font-mono text-cyan-400">3 次</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">本地快取格式 (Cache Storage)</span>
                <span className="font-mono text-slate-300">Parquet / Local Snapshot</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">降級模式策略 (Degraded Mode)</span>
                <span className="font-mono text-amber-400">Fallback to Climatology Norm</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Manual Payload Tester */}
      <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Play className="h-5 w-5 text-indigo-400" />
              <CardTitle className="text-base font-semibold text-slate-200">
                手動推論測試 (Payload Tester)
              </CardTitle>
            </div>
            {isSuccess === true && (
              <Badge variant="success" className="gap-1">
                <CheckCircle2 className="h-3 w-3" /> 200 OK
              </Badge>
            )}
            {isSuccess === false && (
              <Badge variant="destructive" className="gap-1">
                <XCircle className="h-3 w-3" /> Error
              </Badge>
            )}
          </div>
          <CardDescription>
            發送 POST /predict 請求以測試模型響應與結構
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-xs">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-slate-400 font-medium">Horizon Hours (1-168)</label>
              <input
                type="number"
                min={1}
                max={168}
                value={testHorizon}
                onChange={(e) => setTestHorizon(Number(e.target.value))}
                className="w-full bg-slate-950/80 border border-slate-800 rounded-lg px-3 py-2 text-slate-300 font-mono"
              />
            </div>
          </div>

          <Button
            onClick={handleTestInference}
            disabled={loading}
            className="w-full gap-2 text-xs"
          >
            {loading ? (
              <RefreshCw className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            發送推論請求 (Execute Prediction)
          </Button>

          {result && (
            <div className="space-y-1.5 pt-2">
              <label className="text-slate-400 font-medium">回應結果 (JSON Response)</label>
              <pre className="max-h-48 overflow-y-auto rounded-lg border border-slate-800 bg-slate-950 p-3 font-mono text-[11px] text-cyan-300">
                {result}
              </pre>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
