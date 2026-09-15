#!/bin/sh
# The host scripts directory is also mounted at /app/scripts in ingestion.
# Keep the maintenance marker outside Git; moving it aside resumes execution.
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -e "$script_dir/.sclib-ingestion-paused" ]; then
    printf '%s\n' 'SCLib ingestion/NER is paused for maintenance; command skipped.'
    exit 0
fi
exec "$@"
