# syntax=docker/dockerfile:1.7
FROM node:20-alpine AS deps
WORKDIR /app
RUN corepack enable
COPY package.json ./
# No lockfile yet during Phase 1 — install fresh. Phase 4 will commit a
# pnpm-lock.yaml and swap this for `pnpm install --frozen-lockfile`.
RUN corepack prepare pnpm@9.12.0 --activate && pnpm install

FROM node:20-alpine AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9.12.0 --activate
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# basePath is read from NEXT_PUBLIC_BASE_PATH at `next build` time and
# baked into every emitted asset URL and link href. Default /sclib
# matches production routing under https://jzis.org/sclib. Override
# with --build-arg NEXT_PUBLIC_BASE_PATH= for a root-mounted dev build.
ARG NEXT_PUBLIC_BASE_PATH=/sclib
ARG NEXT_PUBLIC_API_BASE=https://api.jzis.org/sclib/v1
# GIT_SHA is short commit hash, surfaced on the site footer and
# /version endpoint so users can correlate UI behaviour with a code
# revision. Falls back to "dev" for local builds.
ARG GIT_SHA=dev
ENV NEXT_PUBLIC_BASE_PATH=$NEXT_PUBLIC_BASE_PATH \
    NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_PUBLIC_GIT_SHA=$GIT_SHA \
    NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:20-alpine AS runner
WORKDIR /app
ARG NEXT_PUBLIC_BASE_PATH=/sclib
# Re-declare GIT_SHA in the runner stage so it's also baked into the
# final image's env (Next inlines NEXT_PUBLIC_* at build, but a few
# server-side reads use process.env at runtime — keeping both is
# safer than discovering a divergence later).
ARG GIT_SHA=dev
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_BASE_PATH=$NEXT_PUBLIC_BASE_PATH \
    NEXT_PUBLIC_GIT_SHA=$GIT_SHA \
    GIT_SHA=$GIT_SHA \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
