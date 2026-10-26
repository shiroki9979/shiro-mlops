import { useHealth } from '@/hooks/use-health'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Moon,
  RefreshCw,
  Sun,
} from 'lucide-react'
import { useState } from 'react'
import { useMessages } from '@/i18n/use-messages'

export function Header() {
  const { data: health, isLoading, isError, refetch, isFetching } = useHealth()
  const [isDark, setIsDark] = useState(true)
  const m = useMessages()

  const toggleTheme = () => {
    setIsDark(!isDark)
    document.documentElement.classList.toggle('dark')
    document.documentElement.classList.toggle('light')
  }

  return (
    <header className="h-16 border-b border-slate-800 bg-slate-950/60 px-6 flex items-center justify-between backdrop-blur-md sticky top-0 z-40">
      <div className="flex items-center gap-4">
        <h2 className="text-sm font-semibold text-slate-200">
          {m.header.title}
        </h2>
        <span className="text-xs text-slate-500">|</span>
        <span className="text-xs text-slate-400 font-mono">{m.header.engine}</span>
      </div>

      <div className="flex items-center gap-3">
        {/* Backend health status badge */}
        {isLoading ? (
          <Badge variant="secondary" className="gap-1.5 py-1">
            <Activity className="h-3.5 w-3.5 animate-spin text-slate-400" />
            <span>{m.header.checkingHealth}</span>
          </Badge>
        ) : isError || !health?.model_loaded ? (
          <Badge variant="destructive" className="gap-1.5 py-1">
            <AlertTriangle className="h-3.5 w-3.5" />
            <span>{isError ? m.header.apiUnreachable : m.header.modelNotLoaded}</span>
          </Badge>
        ) : (
          <Badge variant="success" className="gap-1.5 py-1">
            <CheckCircle2 className="h-3.5 w-3.5" />
            <span>{m.header.apiHealthy(health.environment, health.version)}</span>
          </Badge>
        )}

        {/* Manual Refresh Button */}
        <Button
          variant="outline"
          size="sm"
          onClick={() => refetch()}
          disabled={isFetching}
          className="gap-1.5 text-xs text-slate-300 border-slate-800 hover:bg-slate-850"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin text-cyan-400' : ''}`}
          />
          <span>{m.common.refresh}</span>
        </Button>

        {/* Theme Toggle */}
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          className="h-8 w-8 text-slate-400 hover:text-slate-200"
          title={m.header.toggleTheme}
        >
          {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
      </div>
    </header>
  )
}
