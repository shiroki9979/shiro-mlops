import { createRouter, type RouterHistory } from '@tanstack/react-router'
import { routeTree } from './routeTree'

// One factory for main.tsx and the tests, so both build the router the same way.
export function createAppRouter(history?: RouterHistory) {
  return createRouter({ routeTree, history })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
