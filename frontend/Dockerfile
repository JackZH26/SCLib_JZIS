# syntax=docker/dockerfile:1.7
FROM node:25-alpine AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN corepack prepare pnpm@9.12.0 --activate && pnpm install --frozen-lockfile

FROM node:25-alpine AS builder
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
ARG NEXT_PUBLIC_WEB_VITALS_SAMPLE_RATE=0.1
# GIT_SHA is short commit hash, surfaced on the site footer and
# /version endpoint so users can correlate UI behaviour with a code
# revision. Falls back to "dev" for local builds.
ARG GIT_SHA=dev
ENV NEXT_PUBLIC_BASE_PATH=$NEXT_PUBLIC_BASE_PATH \
    NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_PUBLIC_WEB_VITALS_SAMPLE_RATE=$NEXT_PUBLIC_WEB_VITALS_SAMPLE_RATE \
    NEXT_PUBLIC_GIT_SHA=$GIT_SHA \
    NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:25-alpine AS runner
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
# Refresh the small Alpine runtime to fixed repository packages, then remove
# npm/Corepack/Yarn. The standalone Next.js server only needs `node`; retaining
# package managers would expose their large vendored dependency trees at
# runtime without providing an operational capability.
RUN apk upgrade --no-cache \
 && rm -rf /usr/local/lib/node_modules/npm \
 && rm -f \
      /usr/local/bin/npm \
      /usr/local/bin/npx \
      /usr/local/bin/corepack \
      /usr/local/bin/yarn \
      /usr/local/bin/yarnpkg
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
