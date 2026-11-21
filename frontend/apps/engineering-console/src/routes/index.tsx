import { createRoute, redirect } from '@tanstack/react-router'
import { rootRoute } from './__root'

// The console has no landing page of its own; its root opens monitoring.
export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  beforeLoad: () => {
    throw redirect({ to: '/monitoring', replace: true })
  },
})
