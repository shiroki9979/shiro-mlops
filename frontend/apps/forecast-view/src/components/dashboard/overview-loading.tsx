import { Card, CardContent, CardHeader, CardTitle } from '@shiro-mlops/shared/ui/card'
import { useMessages } from '@/i18n/messages'

export function OverviewLoading() {
  const { chart, table } = useMessages().dashboard
  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {[1, 2, 3].map((i) => (
          <Card key={i} className="animate-pulse bg-slate-900/50 border-slate-800">
            <CardContent className="p-5 space-y-3">
              <div className="h-4 w-24 bg-slate-800 rounded" />
              <div className="h-8 w-32 bg-slate-800 rounded" />
              <div className="h-3 w-40 bg-slate-800 rounded" />
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader>
          <CardTitle className="text-base font-semibold text-slate-200">{chart.loadingTitle}</CardTitle>
        </CardHeader>
        <CardContent className="h-[420px] flex items-center justify-center">
          <div className="text-center space-y-2">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-cyan-500 border-t-transparent mx-auto" />
            <p className="text-xs text-slate-400">{chart.loading}</p>
          </div>
        </CardContent>
      </Card>

      <Card className="border-slate-800 bg-slate-900/60">
        <CardHeader>
          <CardTitle className="text-base font-semibold text-slate-200">{table.loadingTitle}</CardTitle>
        </CardHeader>
        <CardContent className="h-48 flex items-center justify-center text-xs text-slate-500">
          {table.loading}
        </CardContent>
      </Card>
    </>
  )
}
