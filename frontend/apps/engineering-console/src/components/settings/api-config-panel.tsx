import { useState } from 'react'
import { useMutation, type UseMutationResult } from '@tanstack/react-query'
import { apiClient } from '@/lib/api-client'
import { Badge } from '@shiro-mlops/shared/ui/badge'
import { Button } from '@shiro-mlops/shared/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import { CheckCircle2, Play, RefreshCw, Server, XCircle } from 'lucide-react'
import { type Messages, useMessages } from '@/i18n/messages'
import type { PredictionResponse } from '@/schemas/api'

function testerResponseText(
  testInference: UseMutationResult<PredictionResponse, Error, number>,
  testerText: Messages['settings']['tester'],
): string | null {
  switch (testInference.status) {
    case 'success':
      return JSON.stringify(testInference.data, null, 2)
    case 'error':
      return testerText.error(testInference.error.message)
    default:
      return null
  }
}

export function ApiConfigPanel() {
  const m = useMessages()
  const [testHorizon, setTestHorizon] = useState(24)
  const testInference = useMutation({
    mutationFn: (horizonHours: number) => apiClient.predict({ horizon_hours: horizonHours }),
    // WHY-NOT(networkMode): the default 'online' holds the POST as paused while the browser reports
    // offline, leaving the tester stuck in pending; the console calls a same-origin local API that may
    // still answer then, so send anyway and let an unreachable API surface as a failure.
    networkMode: 'always',
  })
  const responseText = testerResponseText(testInference, m.settings.tester)

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
            {testInference.isSuccess && (
              <Badge variant="success" className="gap-1">
                <CheckCircle2 className="h-3 w-3" /> {m.settings.tester.success}
              </Badge>
            )}
            {testInference.isError && (
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
            onClick={() => testInference.mutate(testHorizon)}
            disabled={testInference.isPending}
            className="w-full gap-2 text-xs"
          >
            {testInference.isPending ? (
              <RefreshCw className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            {m.settings.tester.submit}
          </Button>

          {responseText && (
            <div className="space-y-1.5 pt-2">
              <label className="text-slate-400 font-medium">{m.settings.tester.response}</label>
              <pre className="max-h-48 overflow-y-auto rounded-lg border border-slate-800 bg-slate-950 p-3 font-mono text-[11px] text-cyan-300">
                {responseText}
              </pre>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
