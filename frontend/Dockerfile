FROM node:24.19.0-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43 AS build

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
FROM nginx:1.30.8-alpine@sha256:6437a63b5c529f0e06162b3f593c0154cff6fa2ea0f94fd7c27928cb399e022d
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/forecast-view/dist /usr/share/nginx/html
# Must match the console's Vite `base` and the /console/ locations in nginx.conf.
COPY --from=build /app/apps/engineering-console/dist /usr/share/nginx/html/console
