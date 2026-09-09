import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { ExplorerPage } from '@/components/data-explorer/explorer-page'
import { datasetById } from '@/components/data-explorer/catalog'

export const dataPowerSupplyDemandRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/data/power/supply-demand',
  component: () => <ExplorerPage dataset={datasetById('national_supply_demand')} />,
})
