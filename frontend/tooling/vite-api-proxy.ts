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
