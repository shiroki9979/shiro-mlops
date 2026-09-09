import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { ExplorerPage } from '@/components/data-explorer/explorer-page'
import { datasetById } from '@/components/data-explorer/catalog'

export const dataPowerLoadRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/data/power/load',
  component: () => <ExplorerPage dataset={datasetById('hourly_load')} />,
})
