# syntax=docker/dockerfile:1.7
# Same PostgreSQL/Alpine base as the frozen production database, with a
# portable pgvector extension. This image does not migrate or start a database.
ARG POSTGRES_BASE=postgres@sha256:20edbde7749f822887a1a022ad526fde0a47d6b2be9a8364433605cf65099416
FROM ${POSTGRES_BASE} AS patched-base

# Keep the frozen PostgreSQL binary/minor and Alpine branch, while applying
# vendor fixes to its runtime libraries. Release 41449833128 correctly refused
# the original base's fixed high/critical findings. The final image always
# runs as postgres; remove the unused Go-based root privilege-drop helper.
RUN apk upgrade --no-cache \
 && rm /usr/local/bin/gosu \
 && test "$(postgres --version)" = "postgres (PostgreSQL) 16.13" \
 && test "$(id -u postgres)" = 70 \
 && test "$(id -g postgres)" = 70

FROM patched-base AS extension

ARG PGVECTOR_COMMIT=f37c13f68b57d2c3472b2214fbcff699d6d34876
ARG PGVECTOR_SOURCE_SHA256=83d673c3b287cddbf3879f86215f043f2c2b56c69d37b2a77504910db1ed6e56
RUN apk add --no-cache build-base curl ca-certificates \
 && curl --fail --show-error --location \
      "https://codeload.github.com/pgvector/pgvector/tar.gz/${PGVECTOR_COMMIT}" \
      --output /tmp/pgvector.tar.gz \
 && printf '%s  %s\n' "${PGVECTOR_SOURCE_SHA256}" /tmp/pgvector.tar.gz | sha256sum -c - \
 && mkdir /tmp/pgvector \
 && tar -xzf /tmp/pgvector.tar.gz --strip-components=1 -C /tmp/pgvector \
 && make -C /tmp/pgvector -j2 OPTFLAGS="" with_llvm=no \
 && make -C /tmp/pgvector install DESTDIR=/stage OPTFLAGS="" with_llvm=no

FROM patched-base
COPY --from=extension /stage/usr/local/ /usr/local/
LABEL org.opencontainers.image.title="SCLib PostgreSQL 16.13 with pgvector 0.8.7" \
      org.jzis.sclib.postgres.version="16.13" \
      org.jzis.sclib.pgvector.version="0.8.7" \
      org.jzis.sclib.pgvector.source="f37c13f68b57d2c3472b2214fbcff699d6d34876"

# The frozen base owns PGDATA and its socket directory as postgres. Existing
# production volumes must retain that ownership; do not broaden permissions.
USER postgres
