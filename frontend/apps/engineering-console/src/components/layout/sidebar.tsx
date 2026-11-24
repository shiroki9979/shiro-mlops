import { Link, useRouterState } from '@tanstack/react-router'
import {
  Activity,
  Database,
  Flame,
  Radio,
  Settings,
  Zap,
} from 'lucide-react'
import { cn } from '@shiro-mlops/shared/utils'
import { type ServiceState, serviceStateOf, useHealth } from '@/hooks/use-health'
import {
  EXPLORER_DATASETS,
  EXPLORER_NAV_GROUPS,
  type ExplorerDatasetConfig,
} from '@/components/data-explorer/catalog'
import { type Messages, useMessages } from '@/i18n/messages'

interface NavItem {
  to: '/monitoring' | '/settings' | '/data'
  labelKey: keyof Messages['nav']
  icon: typeof Activity
}

const navItems: NavItem[] = [
  {
    to: '/monitoring',
    labelKey: 'monitoring',
    icon: Activity,
  },
  {
    to: '/data',
    labelKey: 'dataExplorer',
    icon: Database,
  },
  {
    to: '/settings',
    labelKey: 'settings',
    icon: Settings,
  },
]

const explorerGroups = EXPLORER_NAV_GROUPS.map((group) => ({
  id: group,
  datasets: EXPLORER_DATASETS.filter((dataset) => dataset.navGroup === group),
}))

function isDatasetActive(
  dataset: ExplorerDatasetConfig,
  pathname: string,
  search: Record<string, unknown>,
): boolean {
  if (pathname !== dataset.path) return false
  if (!dataset.search?.type) return true
  return search.type === dataset.search.type
}

function ExplorerNavigation({ pathname, search }: { pathname: string; search: Record<string, unknown> }) {
  const m = useMessages()
  return (
    <div className="ml-4 border-l border-slate-800 pl-2 space-y-2">
      {explorerGroups.map((group) => (
        <div key={group.id} className="space-y-0.5">
          <div className="px-2 pt-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            {m.explorer.navGroups[group.id]}
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
              {m.explorer.datasets[dataset.id].label}
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
  search: Record<string, unknown>
  explorerEnabled: boolean
}) {
  const m = useMessages()
  const items = navItems.filter((item) => item.to !== '/data' || explorerEnabled)

  return (
    <nav className="space-y-1.5">
      <div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
        {m.nav.sectionTitle}
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
                <span>{m.nav[item.labelKey]}</span>
              </div>
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

type ServiceStatusText = Messages['serviceStatus']
type ApiStateKey = keyof ServiceStatusText['apiState']
type ModelStateKey = keyof ServiceStatusText['modelState']

const API_ROW = {
  healthy: { state: 'reachable', tone: 'text-emerald-400' },
  modelNotLoaded: { state: 'reachable', tone: 'text-emerald-400' },
  unreachable: { state: 'unreachable', tone: 'text-rose-400' },
  checking: { state: 'checking', tone: 'text-slate-500' },
} as const satisfies Record<ServiceState['kind'], { state: ApiStateKey; tone: string }>

const MODEL_ROW = {
  healthy: { state: 'loaded', tone: 'text-cyan-400' },
  modelNotLoaded: { state: 'notLoaded', tone: 'text-rose-400' },
  unreachable: { state: 'unknown', tone: 'text-slate-500' },
  checking: { state: 'checking', tone: 'text-slate-500' },
} as const satisfies Record<ServiceState['kind'], { state: ModelStateKey; tone: string }>

function SidebarStatusCard({ service }: { service: ServiceState }) {
  const text = useMessages().serviceStatus
  const api = API_ROW[service.kind]
  const model = MODEL_ROW[service.kind]
  return (
    <section
      aria-label={text.label}
      className="rounded-xl border border-slate-800/80 bg-slate-900/50 p-3.5 space-y-2 mt-4 shrink-0"
    >
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="text-slate-400 flex items-center gap-1.5">
          <Radio className={cn('h-3.5 w-3.5 shrink-0', api.tone, service.kind === 'healthy' && 'animate-pulse')} />
          {text.api}
        </span>
        <span className={cn('text-[11px] font-mono', api.tone)}>{text.apiState[api.state]}</span>
      </div>
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="text-slate-400 flex items-center gap-1.5">
          <Flame className={cn('h-3.5 w-3.5 shrink-0', model.tone)} />
          {text.model}
        </span>
        <span className={cn('text-[11px] font-mono', model.tone)}>{text.modelState[model.state]}</span>
      </div>
    </section>
  )
}

export function Sidebar() {
  const router = useRouterState()
  const healthQuery = useHealth()
  const explorerEnabled = healthQuery.data?.data_explorer_enabled ?? false
  const m = useMessages()

  return (
    <aside className="w-64 shrink-0 border-r border-slate-800 bg-slate-950/80 p-4 flex flex-col justify-between backdrop-blur-xl h-screen sticky top-0">
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
        <SidebarNavigation
          pathname={router.location.pathname}
          search={router.location.search}
          explorerEnabled={explorerEnabled}
        />
      </div>
      <SidebarStatusCard service={serviceStateOf(healthQuery)} />
    </aside>
  )
}
