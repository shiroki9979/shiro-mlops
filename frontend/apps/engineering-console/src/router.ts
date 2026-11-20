import { createRouter, type RouterHistory } from '@tanstack/react-router'
import { routeTree } from './routeTree'

// One factory for main.tsx and the tests, so both mount the routes under the same base path.
export function createAppRouter(history?: RouterHistory) {
  return createRouter({ routeTree, history, basepath: import.meta.env.BASE_URL })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
