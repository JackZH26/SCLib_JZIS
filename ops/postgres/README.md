# PostgreSQL and pgvector migration runtime

This image extends the exact production PostgreSQL 16.13 Alpine image with
pgvector 0.8.7. The base digest, upstream source commit and archive SHA-256 are
frozen in the Dockerfile. Portable compilation avoids host-specific CPU flags.
The final stage contains the extension, not the compiler or download tools.

```sh
docker build --tag sclib-pgvector:16.13-0.8.7 --file ops/postgres/Dockerfile ops/postgres
docker image inspect sclib-pgvector:16.13-0.8.7 --format '{{.Id}}'
```

The Test workflow builds this image and runs actual binary float32 roundtrip,
cosine/HNSW filtering and invalid-input checks in fresh owned services. The
Release images workflow publishes and signs the PostgreSQL digest after the
existing Test and Security gates. This does not switch production PostgreSQL.
Set `POSTGRES_IMAGE` to a verified signed digest only in the later, rehearsed
maintenance operation. Never use the original image after vector types exist.

The ordinary test runner still defaults to its original PostgreSQL image.
An opt-in test accepts only a preinstalled immutable local image ID, creates new
private services, installs the extension using its own bootstrap connection,
verifies the capability and destroys only those services on completion:

```sh
api/.venv/bin/python scripts/run_disposable_tests.py --backend docker \
  --postgres-image sha256:<local-image-id> --pgvector --suite api \
  -- -q tests/test_pgvector_runtime.py
```

On a Mac with PostgreSQL binaries, compile the same extension into that
user-owned runtime and use `--backend native --postgres-bin ... --redis-bin ...
--pgvector`. Record the actual server version; a native 16.15 test does not prove
Linux/musl 16.13 parity. Do not install into a system PostgreSQL using sudo.

The capacity tool `scripts/pgvector_rehearsal.py` operates only on a retained
network-isolated production-backup drill with a completed restore receipt.
It checks the exact image/container/volume ownership before opening SQL. It is
not an application adapter, production migration or activation tool. Never run
API pytest on that restored database.

```sh
python3 scripts/pgvector_rehearsal.py \
  --restore-report /private/run/production-backup-restore.json \
  --source-generation <exact-generation-uuid> --manifest <source-manifest-sha256>
# Repeat with --phase import --apply, --phase verify, then --phase build --apply.
```

Import uses bounded 1,000-member batches and a durable projection cursor.
It verifies text/snapshot/evidence/receipt bindings and canonical vector hashes.
The PostgreSQL binary protocol preserves each float32 byte. Completed imports
can resume; conflicting replay is refused. Full verification enumerates both
the projection and declared members and compares PostgreSQL binary readback.
HNSW construction requires full verification and additional measured headroom.
The fixed rehearsal schema is isolated from application content; no command
updates original records, pointers, source permissions or deployment settings.

Keep all reports, backup artifacts and excerpts outside Git. Report capacity
and quality separately: successful copying or an HNSW index does not establish
the migration plan's 200-query recall and end-to-end acceptance gates.
