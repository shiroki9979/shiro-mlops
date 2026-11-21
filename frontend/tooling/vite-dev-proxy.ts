// The `vite dev` stand-in for the Nginx `/api/` gateway (frontend/nginx.conf), used by the Engineering
// Console's vite.config.ts: strips the prefix and forwards to the API that `make dev` serves on port 8000
// (keep in sync with the Makefile `dev` target).
export const apiDevProxy = {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api/, ''),
  },
}

// The `vite dev` stand-in for the `/published/` files that local Nginx serves (frontend/nginx.conf):
// forwards the path unchanged to the Compose frontend port (keep in sync with the `127.0.0.1:8080:80`
// mapping in docker/docker-compose.yml). Only the Forecast View reads `/published/`.
export const publishedDevProxy = {
  '/published': {
    target: 'http://localhost:8080',
    changeOrigin: true,
  },
}
