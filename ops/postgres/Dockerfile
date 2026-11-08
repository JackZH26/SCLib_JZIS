# syntax=docker/dockerfile:1.7
ARG POSTGRES_BASE=postgres@sha256:20edbde7749f822887a1a022ad526fde0a47d6b2be9a8364433605cf65099416
FROM ${POSTGRES_BASE}

# Keep the frozen PostgreSQL binary/minor and Alpine branch, while applying
# vendor fixes to its runtime libraries. Release 41449833128 correctly refused
# the original base's fixed high/critical findings. The final image always
# runs as postgres; remove the unused Go-based root privilege-drop helper.
RUN apk upgrade --no-cache \
 && rm /usr/local/bin/gosu \
 && test "$(postgres --version)" = "postgres (PostgreSQL) 16.13" \
 && test "$(id -u postgres)" = 70 \
 && test "$(id -g postgres)" = 70

LABEL org.opencontainers.image.title="SCLib PostgreSQL 16.13" \
      org.jzis.sclib.postgres.version="16.13"

USER postgres
