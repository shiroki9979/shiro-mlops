import { createRootRoute, Outlet } from '@tanstack/react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AppLayout } from '@/components/layout/app-layout'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from 'sonner'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 30000,
    },
  },
})

export const rootRoute = createRootRoute({
  component: () => (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <AppLayout>
          <Outlet />
        </AppLayout>
        <Toaster richColors position="top-right" theme="dark" />
      </TooltipProvider>
    </QueryClientProvider>
  ),
})
