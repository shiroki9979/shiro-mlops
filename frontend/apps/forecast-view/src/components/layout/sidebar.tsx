import { Link, useRouterState } from '@tanstack/react-router'
import { BarChart3, LayoutDashboard, Zap } from 'lucide-react'
import { cn } from '@shiro-mlops/shared/utils'
import { type Messages, useMessages } from '@/i18n/messages'

interface NavItem {
  to: '/' | '/history'
  labelKey: 'dashboard' | 'history'
  icon: typeof LayoutDashboard
  live?: boolean
}

const navItems: NavItem[] = [
  {
    to: '/',
    labelKey: 'dashboard',
    icon: LayoutDashboard,
    live: true,
  },
  {
    to: '/history',
    labelKey: 'history',
    icon: BarChart3,
  },
]

function SidebarNavigation({ pathname, m }: { pathname: string; m: Messages }) {
  return (
    <nav className="space-y-1.5">
      <div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        {m.nav.sectionTitle}
      </div>
      {navItems.map((item) => {
        const Icon = item.icon
        const isActive = pathname === item.to

        return (
          <Link
            key={item.to}
            to={item.to}
            className={cn(
              'flex items-center justify-between rounded-lg px-3 py-2.5 text-sm font-medium transition-all group',
              isActive
                ? 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 shadow-sm'
                : 'text-slate-400 hover:bg-slate-900/60 hover:text-slate-200 border border-transparent',
            )}
          >
            <div className="flex items-center gap-3">
              <Icon
                className={cn(
                  'h-4 w-4 transition-colors',
                  isActive ? 'text-cyan-400' : 'text-slate-500 group-hover:text-slate-300',
                )}
              />
              <span>{m.nav[item.labelKey]}</span>
            </div>
            {item.live && (
              <span className="flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
                {m.nav.liveBadge}
              </span>
            )}
          </Link>
        )
      })}
    </nav>
  )
}

export function Sidebar() {
  const router = useRouterState()
  const m = useMessages()

  return (
    <aside className="w-64 shrink-0 border-r border-slate-800 bg-slate-950/80 p-4 flex flex-col backdrop-blur-xl h-screen sticky top-0">
      <div className="space-y-6 min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="flex items-center gap-3 px-2 py-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-cyan-600 to-cyan-400 text-slate-950 font-bold shadow-lg shadow-cyan-500/20">
            <Zap className="h-6 w-6 fill-slate-950 stroke-slate-950" />
          </div>
          <div>
            <h1 className="font-bold text-base tracking-wide text-slate-100 flex items-center gap-1.5">
              {m.app.brand}
            </h1>
            <p className="text-xs text-cyan-400/80 font-medium">{m.app.tagline}</p>
          </div>
        </div>
        <SidebarNavigation pathname={router.location.pathname} m={m} />
      </div>
    </aside>
  )
}
