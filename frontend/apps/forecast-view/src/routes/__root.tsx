import { useState } from 'react'
import { createRootRoute, Outlet } from '@tanstack/react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AppLayout } from '@/components/layout/app-layout'
import { TooltipProvider } from '@shiro-mlops/shared/ui/tooltip'
import { Toaster } from 'sonner'

function RootLayout() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            staleTime: 30000,
          },
        },
      }),
  )

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <AppLayout>
          <Outlet />
        </AppLayout>
        <Toaster richColors position="top-right" theme="dark" />
      </TooltipProvider>
    </QueryClientProvider>
  )
}

export const rootRoute = createRootRoute({
  component: RootLayout,
})
