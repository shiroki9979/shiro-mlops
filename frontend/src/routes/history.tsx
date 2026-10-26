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
  const text = useMessages().history
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <History className="h-5 w-5 text-cyan-400" />
            {text.title}
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            {text.description}
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
            {text.conclusionTitle}
          </CardTitle>
        </CardHeader>
        <CardContent className="text-xs text-slate-400 space-y-2 leading-relaxed">
          <p>{text.conclusionAccuracy}</p>
          <p>{text.conclusionPeak}</p>
        </CardContent>
      </Card>
    </div>
  )
}
