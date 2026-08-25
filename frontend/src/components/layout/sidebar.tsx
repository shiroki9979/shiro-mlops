import { Link, useRouterState } from '@tanstack/react-router'
import {
  Activity,
  BarChart3,
  Flame,
  LayoutDashboard,
  Radio,
  Settings,
  Zap,
} from 'lucide-react'
import { cn } from '@/lib/utils'

interface NavItem {
  to: '/' | '/history' | '/monitoring' | '/settings'
  label: string
  icon: typeof LayoutDashboard
  badge?: string
}

const navItems: NavItem[] = [
  {
    to: '/',
    label: '即時預測總覽',
    icon: LayoutDashboard,
    badge: 'Live',
  },
  {
    to: '/history',
    label: '歷史回測與評估',
    icon: BarChart3,
  },
  {
    to: '/monitoring',
    label: '模型漂移監控',
    icon: Activity,
  },
  {
    to: '/settings',
    label: '系統連線設定',
    icon: Settings,
  },
]

export function Sidebar() {
  const router = useRouterState()
  const currentPath = router.location.pathname

  return (
    <aside className="w-64 shrink-0 border-r border-slate-800 bg-slate-950/80 p-4 flex flex-col justify-between backdrop-blur-xl h-screen sticky top-0">
      <div className="space-y-6">
        {/* Brand Logo */}
        <div className="flex items-center gap-3 px-2 py-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-cyan-600 to-cyan-400 text-slate-950 font-bold shadow-lg shadow-cyan-500/20">
            <Zap className="h-6 w-6 fill-slate-950 stroke-slate-950" />
          </div>
          <div>
            <h1 className="font-bold text-base tracking-wide text-slate-100 flex items-center gap-1.5">
              shiro-mlops
            </h1>
            <p className="text-xs text-cyan-400/80 font-medium">電力負載動態預測</p>
          </div>
        </div>

        {/* Navigation */}
        <nav className="space-y-1.5">
          <div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            核心功能
          </div>
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive = currentPath === item.to

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
                      isActive
                        ? 'text-cyan-400'
                        : 'text-slate-500 group-hover:text-slate-300',
                    )}
                  />
                  <span>{item.label}</span>
                </div>
                {item.badge && (
                  <span className="flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                    <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
                    {item.badge}
                  </span>
                )}
              </Link>
            )
          })}
        </nav>
      </div>

      {/* System Status card in bottom sidebar */}
      <div className="rounded-xl border border-slate-800/80 bg-slate-900/50 p-3.5 space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-400 flex items-center gap-1.5">
            <Radio className="h-3.5 w-3.5 text-emerald-400 animate-pulse" />
            台電即時串接
          </span>
          <span className="text-[11px] text-emerald-400 font-mono">NORMAL</span>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-400 flex items-center gap-1.5">
            <Flame className="h-3.5 w-3.5 text-cyan-400" />
            LightGBM 遞迴推論
          </span>
          <span className="text-[11px] text-cyan-400 font-mono">ACTIVE</span>
        </div>
      </div>
    </aside>
  )
}
