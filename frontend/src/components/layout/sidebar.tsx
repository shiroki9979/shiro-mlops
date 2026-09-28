import { Link, useRouterState } from '@tanstack/react-router'
import {
  Activity,
  BarChart3,
  Database,
  Flame,
  LayoutDashboard,
  Radio,
  Settings,
  Zap,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useHealth } from '@/hooks/use-health'
import {
  EXPLORER_DATASETS,
  EXPLORER_NAV_GROUPS,
  type ExplorerDatasetConfig,
} from '@/components/data-explorer/catalog'

interface NavItem {
  to: '/' | '/history' | '/monitoring' | '/settings' | '/data'
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
    to: '/data',
    label: '營運資料檢視器',
    icon: Database,
  },
  {
    to: '/settings',
    label: '系統連線設定',
    icon: Settings,
  },
]

const explorerGroups = EXPLORER_NAV_GROUPS.map((group) => ({
  ...group,
  datasets: EXPLORER_DATASETS.filter((dataset) => dataset.navGroup === group.id),
}))

function searchType(search: unknown): string | null {
  if (typeof search === 'object' && search && 'type' in search) {
    const type = (search as { type?: unknown }).type
    return typeof type === 'string' ? type : null
  }
  if (typeof search === 'string' && search) {
    return new URLSearchParams(search.startsWith('?') ? search : `?${search}`).get('type')
  }
  return null
}

function isDatasetActive(
  dataset: ExplorerDatasetConfig,
  pathname: string,
  search: unknown,
): boolean {
  if (pathname !== dataset.path) return false
  if (!dataset.search?.type) return true
  return searchType(search) === dataset.search.type
}

function ExplorerNavigation({ pathname, search }: { pathname: string; search: unknown }) {
  return (
    <div className="ml-4 border-l border-slate-800 pl-2 space-y-2">
      {explorerGroups.map((group) => (
        <div key={group.id} className="space-y-0.5">
          <div className="px-2 pt-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            {group.label}
          </div>
          {group.datasets.map((dataset) => (
            <Link
              key={dataset.id}
              to={dataset.path}
              search={dataset.search}
              className={cn(
                'block rounded-md px-2 py-1.5 text-xs font-medium transition-colors',
                isDatasetActive(dataset, pathname, search)
                  ? 'bg-cyan-500/10 text-cyan-300'
                  : 'text-slate-400 hover:bg-slate-900/60 hover:text-slate-200',
              )}
            >
              {dataset.label}
            </Link>
          ))}
        </div>
      ))}
    </div>
  )
}

function SidebarNavigation({
  pathname,
  search,
  explorerEnabled,
}: {
  pathname: string
  search: unknown
  explorerEnabled: boolean
}) {
  const items = navItems.filter((item) => item.to !== '/data' || explorerEnabled)

  return (
    <nav className="space-y-1.5">
      <div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        核心功能
      </div>
      {items.map((item) => {
        const Icon = item.icon
        const isActive = item.to === '/data' ? pathname.startsWith('/data') : pathname === item.to

        return (
          <div key={item.to} className="space-y-1">
            <Link
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
                <span>{item.label}</span>
              </div>
              {item.badge && (
                <span className="flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                  <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
                  {item.badge}
                </span>
              )}
            </Link>
            {item.to === '/data' && explorerEnabled && (
              <ExplorerNavigation pathname={pathname} search={search} />
            )}
          </div>
        )
      })}
    </nav>
  )
}

function SidebarStatusCard() {
  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-900/50 p-3.5 space-y-2 mt-4 shrink-0">
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
  )
}

export function Sidebar() {
  const router = useRouterState()
  const { data: health } = useHealth()
  const explorerEnabled = health?.data_explorer_enabled ?? false

  return (
    <aside className="w-64 shrink-0 border-r border-slate-800 bg-slate-950/80 p-4 flex flex-col justify-between backdrop-blur-xl h-screen sticky top-0">
      <div className="space-y-6 min-h-0 flex-1 overflow-y-auto pr-1">
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
        <SidebarNavigation
          pathname={router.location.pathname}
          search={router.location.search}
          explorerEnabled={explorerEnabled}
        />
      </div>
      <SidebarStatusCard />
    </aside>
  )
}
