# Owned restored-corpus preparation

`python -m services.retrieval_corpus_operator` prepares a real corpus on an
independently verified, isolated restore. It is an engineering rehearsal, not
an API deployment or a quality acceptance. It cannot activate a backend.

The host operator must verify the signed PostgreSQL image, owned restored
volume, network isolation, source custody and primary-service health before
starting. Use the exact tracked API source and locked dependencies. Never run
pytest against the restored database. Run tests only through the disposable
test runner.

The CLI accepts no database URL argument. Its environment must identify
`sclib_restore_drill` in a non-production environment. It also requires the
owned restore marker, exact immutable source generation/hash/count,
PostgreSQL 16, pgvector 0.8.7 and builder membership. Default execution previews
every phase without writing. Run the schema lifecycle migration separately
on the verified owned restore before using this CLI.

Supply `--generation-id`, `--manifest-sha256`, `--expected-members`,
`--build-id`, `--image-digest` and `--implementation-revision` explicitly.
The image digest describes the PostgreSQL runtime and requires independent
signature verification. Execute these phases in order with `--apply`:

1. `content`, `copy-content`, `seal-content`
2. `projection`, `copy-vectors`
3. `graph`, `seal-projection`, `validate`

`validate` also requires a new explicit `--validation-id`. Each bounded COPY
partition commits separately. Replaying COPY enumerates and verifies actual
existing rows; a cursor or previous receipt cannot substitute for readback.
The initial vector COPY includes the year, avoiding a second full heap update.

Full-corpus `graph` additionally requires `--host-graph-budget`. This flag is
an acknowledgement by a separate host guard, not an automatic health check.
The guard must reserve disk/RAM/CPU, monitor the primary and cancel only this
build's backend on failure. Its application name is
`sclib_corpus_graph_<build UUID without hyphens>`. Graph construction uses a
per-build fence, 6 GiB maintenance memory and at most five parallel workers;
it does not hold the global source fence. An existing graph is never silently
rebuilt; sealing validates its actual catalog identity and options.

Keep all failures and source/physical readback evidence. Do not create quality
acceptance rows, change the active pointer, route public traffic or retire the
current Google deployment through this procedure. Those actions still require
the separate relevance, complete-service, recovery, load and observation gates.

Validation for the initial implementation: 47 checks passed on freshly owned
native PostgreSQL/vector services, covering preview safety, identity rejection,
COPY replay, unchanged v1 data, sealing and complete vector validation. The
host-scale graph is exercised separately on the owned full restore.
