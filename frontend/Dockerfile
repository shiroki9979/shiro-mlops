ARG NODE_VERSION=24.19.0
FROM node:${NODE_VERSION}-alpine AS build

WORKDIR /app
RUN corepack enable
# Manifests first so the dependency layer is reused until a package.json or the lockfile changes.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/forecast-view/package.json apps/forecast-view/
COPY apps/engineering-console/package.json apps/engineering-console/
COPY packages/shared/package.json packages/shared/
RUN node -e "if (process.version.slice(1) !== require('./package.json').engines.node) throw new Error('Node version differs from package.json engines.node')" \
    && corepack pnpm install --frozen-lockfile
COPY . .
RUN corepack pnpm build

# The local image serves both apps on one origin (ADR-0014 §2.5); the cloud deploys only forecast-view.
FROM nginx:1.30-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/forecast-view/dist /usr/share/nginx/html
# Must match the console's Vite `base` and the /console/ locations in nginx.conf.
COPY --from=build /app/apps/engineering-console/dist /usr/share/nginx/html/console
