#!/bin/sh
# Docker entrypoint: run alembic migrations, then exec uvicorn (or whatever
# CMD was given). Idempotent — alembic upgrade head is a no-op when DB is
# already at head.
set -e

if [ "$1" = "uvicorn" ]; then
    echo "[entrypoint] alembic upgrade head"
    alembic upgrade head
fi

exec "$@"
