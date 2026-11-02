# Private pgvector build authority v2

Migration 0109 implements a separate builder's immutable build, physical seal
and full binary readback history. It does not activate a build, change a v1
pointer, integrate a public reader, grant production credentials or qualify a
release for cutover. Apply 0107–0109 only as part of the coordinated API,
migration, ingestion and standby maintenance rehearsal required by the
[migration plan](PGVECTOR_MIGRATION_PLAN.md).

The database requires membership in `sclib_retrieval_builder`, rather than
trusting a Python caller or an accidental table INSERT grant. Production role
provisioning remains a separate operator task. The disposable runner creates
NOLOGIN builder/reader groups only inside its fresh owned vector-enabled
cluster; its test owner remains NOSUPERUSER/NOCREATEDB/NOCREATEROLE. No running
database can be attached to that test runner.

A build requires a sealed complete content version and the exact frozen
[English query policy](PGVECTOR_QUERY_POLICY_V2.md). Its content root, member
count, profile and actual PostgreSQL/extension versions are derived by SQL.
The declared image digest and implementation revision are retained bindings,
not proof of an image signature or of the operator's scientific approval.
Signature verification and actual released-image identity remain external
release gates.

Physical tables live only in `retrieval_projection.b_<canonical UUID hex>`.
Migration refuses an already occupied or foreign-owned reserved schema. A
per-build fence serializes statement writes and sealing without locking the
global source fence. A stale repeatable-read writer receives a serialization
failure instead of missing a newly committed seal. Sealed tables reject even
zero-row DML and TRUNCATE statements. Builder table ownership remains a DDL
privilege; the API runtime must never be an owner or builder member.

`copy_partition` uses an actual sealed partition of at most 1,000 rows and a
4 MiB COPY frame. It checks canonical retained float32 bytes, carries those
bytes directly into PostgreSQL's binary vector representation, derives years
from retained snapshots and reads back every imported binding. There is no
decimal vector serialization. Exact replay verifies current physical rows and
rolls back its temporary epoch change; a partial/conflicting replay fails.
The API-contained `services.pgvector_wire` codec has the same portable framing
as the standalone operator codec; it needs no repository `scripts` directory
in the installed API wheel or image.

The small graph helper refuses more than 1,000 members and has an explicit
64 MiB/no-parallel maintenance budget. Corpus-scale construction requires the
separately budgeted host builder, which is not implemented by this component.
A seal checks actual standalone table columns, primary key, statement guards
and the valid/ready unfiltered cosine HNSW index with m32/ef_construction200.
It records actual table/index OIDs under a private table lock.

Validation requires that same sealed physical pair. SQL independently compares
the complete source and projection inventories, paper/year/text/vector/revision
bindings, origin and content record hashes, every vector byte, and all content
partition manifests. SQL derives its outcome and counts; caller-supplied
`validated` or zero-mismatch claims cannot substitute for readback. Retained
validation does not protect against an administrator later altering DDL;
activation and each reader must resolve/check the retained authority and use
strictly separated privileges.

Services default to preview, use a nested transaction, restore temporary GUCs
and leave the outer commit to their caller. There are no provider requests,
public mutation routes, credential discovery, fallback or activation here.
All build/seal/validation history is append-only. Downgrade refuses retained
history or private physical objects. An empty round trip compares all prior
rows, functions and triggers. Populated rehearsal also verifies unchanged v1
generations/pointers and unchanged private vector bytes/OIDs after a refused
downgrade. Without the owned vector extension, the same schema rehearsal
explicitly records populated projection checks as not run.

Observed locally: 112 joint extension/transport/native/content/backend tests
passed on owned PostgreSQL 16.15; complete schema rehearsals with and without
the extension completed with cleanup verified. These are synthetic boundary
checks. Linux 16.13 CI, corpus builder, activation/CAS, source-use enforcement,
public pins/hydration/history/frontend, real publishing, filtered relevance,
Ask/Similar, service load and full recovery remain separate required gates.
The user's search acceptance scope is English only.
