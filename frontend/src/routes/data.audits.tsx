import { createRoute, useRouterState } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { ExplorerPage } from '@/components/data-explorer/explorer-page'
import { datasetById } from '@/components/data-explorer/catalog'

export const dataAuditsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/data/audits',
  component: AuditsPage,
})

function AuditsPage() {
  const search = useRouterState().location.search as { type?: string }
  const datasetId = search.type === 'forecasts' ? 'cwa_forecast_audits' : 'cwa_observation_audits'
  return <ExplorerPage dataset={datasetById(datasetId)} />
}
