#!/bin/sh
# API startup is schema-read-only. Schema changes belong to the explicit
# one-shot migration service, never restart/scaling of an API container.
set -e

if [ "$1" = "uvicorn" ]; then
    echo "[entrypoint] checking required schema revision (read-only)"
    python -m services.schema_lifecycle check
fi

exec "$@"
