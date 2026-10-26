import { useState } from 'react'
import { apiClient } from '@/lib/api-client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { CheckCircle2, Play, RefreshCw, Server, XCircle } from 'lucide-react'
import { useMessages } from '@/i18n/use-messages'

export function ApiConfigPanel() {
  const m = useMessages()
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
      setResult(m.settings.tester.error(errorMsg))
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
              {m.settings.connection.title}
            </CardTitle>
          </div>
          <CardDescription>
            {m.settings.connection.description}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-xs">
          <div className="space-y-1.5">
            <label htmlFor="api-base-endpoint" className="text-slate-400 font-medium">
              {m.settings.connection.endpointLabel}
            </label>
            <input
              id="api-base-endpoint"
              type="text"
              readOnly
              value={import.meta.env.VITE_API_BASE_URL || m.settings.connection.sameOriginProxy}
              className="w-full bg-slate-950/80 border border-slate-800 rounded-lg px-3 py-2 text-slate-300 font-mono"
            />
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
                {m.settings.tester.title}
              </CardTitle>
            </div>
            {isSuccess === true && (
              <Badge variant="success" className="gap-1">
                <CheckCircle2 className="h-3 w-3" /> {m.settings.tester.success}
              </Badge>
            )}
            {isSuccess === false && (
              <Badge variant="destructive" className="gap-1">
                <XCircle className="h-3 w-3" /> {m.settings.tester.failure}
              </Badge>
            )}
          </div>
          <CardDescription>
            {m.settings.tester.description}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-xs">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label htmlFor="test-horizon-hours" className="text-slate-400 font-medium">
                {m.settings.tester.horizonLabel}
              </label>
              <input
                id="test-horizon-hours"
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
            {m.settings.tester.submit}
          </Button>

          {result && (
            <div className="space-y-1.5 pt-2">
              <label className="text-slate-400 font-medium">{m.settings.tester.response}</label>
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
