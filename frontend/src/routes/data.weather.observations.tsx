import { createRoute } from '@tanstack/react-router'
import { rootRoute } from './__root'
import { ExplorerPage } from '@/components/data-explorer/explorer-page'
import { datasetById } from '@/components/data-explorer/catalog'

export const dataWeatherObservationsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/data/weather/observations',
  component: () => <ExplorerPage dataset={datasetById('cwa_observations')} />,
})
