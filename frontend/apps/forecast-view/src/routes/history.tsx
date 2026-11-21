import { createRoute } from '@tanstack/react-router'
import { History } from 'lucide-react'
import { rootRoute } from './__root'
import { TrackRecordContent } from '@/components/history/track-record'
import { useMessages } from '@/i18n/messages'

export const historyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/history',
  component: HistoryPage,
})

function HistoryPage() {
  const m = useMessages()
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
          <History className="h-5 w-5 text-cyan-400" />
          {m.history.title}
        </h1>
        <p className="text-xs text-slate-400 mt-1">{m.history.description}</p>
      </div>
      <TrackRecordContent />
    </div>
  )
}
