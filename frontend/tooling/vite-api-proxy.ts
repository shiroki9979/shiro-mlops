// The `vite dev` stand-in for the Nginx `/api/` gateway (frontend/nginx.conf), shared by both apps'
// vite.config.ts: strips the prefix and forwards to the API that `make dev` serves on port 8000
// (keep in sync with the Makefile `dev` target).
export const apiDevProxy = {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api/, ''),
  },
}

// The `vite dev` stand-in for the Forecast View's `/published/` reads: forwards the path unchanged to
// the local Compose Nginx, which serves the exported JSON at `/published/` itself. The key keeps the
// trailing slash, so it matches like Nginx `location ^~ /published/` rather than every path that
// starts with `/published` (docs/reference/forecast-view-hosting.md §4). The Engineering Console
// never reads `/published/`.
export const publishedDevProxy = {
  '/published/': {
    target: 'http://localhost:8080',
    changeOrigin: true,
  },
}
