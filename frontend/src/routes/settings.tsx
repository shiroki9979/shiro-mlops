import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { ApiConfigPanel } from '@/components/settings/api-config-panel'
import { Settings } from 'lucide-react'

export const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: SettingsPage,
})

function SettingsPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Settings className="h-5 w-5 text-cyan-400" />
            系統設定與連線診斷 (System Settings & Inference Testing)
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            檢視後端 FastAPI 連線端點（唯讀），並進行手動推論測試。
          </p>
        </div>
      </div>

      <ApiConfigPanel />
    </div>
  )
}
