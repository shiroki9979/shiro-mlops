ARG NODE_VERSION=24.19.0
FROM node:${NODE_VERSION}-alpine AS build

WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN node -e "if (process.version.slice(1) !== require('./package.json').engines.node) throw new Error('Node version differs from package.json engines.node')" \
    && corepack pnpm install --frozen-lockfile
COPY . .
RUN corepack pnpm build

FROM nginx:stable-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
