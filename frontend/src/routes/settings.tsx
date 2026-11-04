import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { ApiConfigPanel } from '@/components/settings/api-config-panel'
import { LanguagePanel } from '@/components/settings/language-panel'
import { useMessages } from '@/i18n/use-messages'
import { Settings } from 'lucide-react'

export const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: SettingsPage,
})

function SettingsPage() {
  const m = useMessages()
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Settings className="h-5 w-5 text-cyan-400" />
            {m.settings.title}
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            {m.settings.description}
          </p>
        </div>
      </div>

      <LanguagePanel />
      <ApiConfigPanel />
    </div>
  )
}
