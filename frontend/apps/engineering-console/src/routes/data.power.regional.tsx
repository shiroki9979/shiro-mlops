import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { ExplorerPage } from '@/components/data-explorer/explorer-page'
import { datasetById } from '@/components/data-explorer/catalog'

export const dataPowerRegionalRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/data/power/regional',
  component: () => <ExplorerPage dataset={datasetById('regional_supply_demand')} />,
})
