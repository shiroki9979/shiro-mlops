import { rootRoute } from './routes/__root'
import { indexRoute } from './routes/index'
import { historyRoute } from './routes/history'
import { monitoringRoute } from './routes/monitoring'
import { settingsRoute } from './routes/settings'

export const routeTree = rootRoute.addChildren([
  indexRoute,
  historyRoute,
  monitoringRoute,
  settingsRoute,
])
