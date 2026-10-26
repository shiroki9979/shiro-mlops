import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { BacktestChart } from '@/components/history/backtest-chart'
import { ErrorMetrics } from '@/components/history/error-metrics'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { History } from 'lucide-react'
import { useMessages } from '@/i18n/use-messages'

export const historyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/history',
  component: HistoryPage,
})

function HistoryPage() {
  const m = useMessages()
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <History className="h-5 w-5 text-cyan-400" />
            {m.history.title}
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            {m.history.description}
          </p>
        </div>
      </div>

      {/* Summary Error Metrics */}
      <ErrorMetrics />

      {/* Backtesting Comparison Curve */}
      <BacktestChart />

      {/* Model Performance Note */}
      <Card className="border-slate-800 bg-slate-900/60 backdrop-blur-md">
        <CardHeader>
          <CardTitle className="text-sm font-semibold text-slate-200">
            {m.history.conclusionTitle}
          </CardTitle>
        </CardHeader>
        <CardContent className="text-xs text-slate-400 space-y-2 leading-relaxed">
          <p>{m.history.conclusionAccuracy}</p>
          <p>{m.history.conclusionPeak}</p>
        </CardContent>
      </Card>
    </div>
  )
}
