# Build only the offline reader. The serving PostgreSQL image never loads it.
FROM ghcr.io/jackzh26/sclib-postgres@sha256:3e4f23b5914cd58094c84ad6f06d8d6ad9e57223e11352dab04b91168100b121 AS compiler
USER root
RUN apk add --no-cache gcc musl-dev
COPY graph_reader.c /tmp/graph_reader.c
RUN gcc -O2 -fPIC -shared -Werror=implicit-function-declaration \
    -I"$(pg_config --includedir-server)" -I"$(pg_config --includedir)/internal" \
    /tmp/graph_reader.c -o /tmp/sclib_frontier_reader.so

FROM scratch
COPY --from=compiler /tmp/sclib_frontier_reader.so /sclib_frontier_reader.so
