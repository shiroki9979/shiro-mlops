import { rootRoute } from './routes/__root'
import { indexRoute } from './routes/index'
import { historyRoute } from './routes/history'
import { monitoringRoute } from './routes/monitoring'
import { settingsRoute } from './routes/settings'
import { dataRoute } from './routes/data'
import { dataPowerLoadRoute } from './routes/data.power.load'
import { dataPowerSupplyDemandRoute } from './routes/data.power.supply-demand'
import { dataPowerRegionalRoute } from './routes/data.power.regional'
import { dataPowerUnitsRoute } from './routes/data.power.units'
import { dataWeatherObservationsRoute } from './routes/data.weather.observations'
import { dataWeatherForecastsRoute } from './routes/data.weather.forecasts'
import { dataAuditsRoute } from './routes/data.audits'

export const routeTree = rootRoute.addChildren([
  indexRoute,
  historyRoute,
  monitoringRoute,
  settingsRoute,
  dataRoute,
  dataPowerLoadRoute,
  dataPowerSupplyDemandRoute,
  dataPowerRegionalRoute,
  dataPowerUnitsRoute,
  dataWeatherObservationsRoute,
  dataWeatherForecastsRoute,
  dataAuditsRoute,
])
