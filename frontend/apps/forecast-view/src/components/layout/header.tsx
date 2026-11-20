import { Button } from '@shiro-mlops/shared/ui/button'
import { LocaleSwitcher } from '@shiro-mlops/shared/i18n/locale-switcher'
import { Moon, Sun } from 'lucide-react'
import { useState } from 'react'
import { useMessages } from '@/i18n/messages'

// The Forecast View shell shows no system state (ADR-0014 §2.4): no API health, environment or version.
export function Header() {
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
        <LocaleSwitcher label={m.localeSwitcher.label} />

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
