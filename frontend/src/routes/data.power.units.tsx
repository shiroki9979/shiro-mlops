import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { ExplorerPage } from '@/components/data-explorer/explorer-page'
import { datasetById } from '@/components/data-explorer/catalog'

export const dataPowerUnitsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/data/power/units',
  component: () => <ExplorerPage dataset={datasetById('unit_generation')} />,
})
