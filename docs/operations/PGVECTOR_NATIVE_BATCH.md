# Native publication batch worker

The separately locked publisher also installs `sclib-stage-native-batch`. It
selects at most100 latest unleased paper jobs, claims distinct expiring tokens,
and stages one immutable content plan from an explicitly sealed base. Only one
publication per paper is selected. Older queued jobs remain retained; the
bounded `supersede` phase records their actual newer successor, without stealing
an unexpired claim or calling old work published.

`claim` defaults to a complete SQL preview and rolls back every claim/content
write. `--apply` requires a new absolute `--plan-out` path, writes a private
mode0600 journal and commits before any graph/provider/filesystem work. A
preexisting journal prevents the transaction from committing. The journal is
an input candidate: actual SQL record hashes, complete content-change inventory,
publication/seal hashes, exact batch/job/claim IDs, worker, newest claim and lease
remain authoritative. A journal left by an interrupted or failed commit cannot
authorize work. All later modes default to read-only preview.

```sh
cd publisher
RETRIEVAL_BACKEND=pgvector uv run --frozen sclib-stage-native-batch \
  --phase claim --logical-index sclib-main --base-content-id BASE_UUID \
  --worker-id native-worker-1 --plan-out /private/batch-1.json --apply
RETRIEVAL_BACKEND=pgvector uv run --frozen sclib-stage-native-batch \
  --phase content --plan /private/batch-1.json --apply
```

`content` enumerates the full allowed base/replacement universe using C-collation
keysets, commits each <=1000-member sealed partition, and then seals the complete
content. It checks the actual claims before each bounded write. An interruption
can resume by enumerating the actual retained partitions; no cursor file is
accepted as evidence that data exists. Changed current claims or newer source
publications stop work. A retry/expired lease requires a new batch/claim identity;
the same immutable publication inputs reuse the content and completed partitions.

`projection` takes explicit build UUID, immutable image digest and implementation
revision. `copy-vectors` copies and compares each complete sealed partition via
the existing binary float32 contract. `small-graph` and `small-validate` are only
for <=1000-member staged corpora. Real corpus graph construction and full
readback must use the separate host runner with observed CPU/RAM/disk, signed
image, primary-health and ownership guards. There is no CLI flag here that
relaxes that limit. Declaring an image digest does not verify its signature.

`retry` records a closed retry reason. `finish` accepts an already existing
activation event and records each job published only if the database confirms
the real current complete native publication. It never creates an acceptance or
activation; a candidate build or legacy activation is insufficient. Exact
finished-operation replay preserves the original receipt. Source writer,
queue-worker, builder and acceptance publisher capabilities remain separate;
source-table read/write grants and production deployment are operator work.

The actual provider preparation/replay, full-corpus host worker integration,
quality/full-site/load/recovery gates and signed production rollout are still
required. This command installs no schedule and resumes no existing ingestion.
It does not download content, call a model/Google ANN, or delete original inputs.

## Guarded full corpus graph phases

The host runner can now select `graph`, `seal-projection`, and `validate` with
`--host-graph-budget`. These phases are closed by default. The host operator
must check the exact database/container and immutable image, source/volume
ownership, disk/RAM/CPU reservation and primary health for the complete phase.
The flag is a host attestation, not an automatic resource measurement.

The graph primitive is shared with the legacy-corpus operator: it requires the
complete inline projection count, uses m=32/ef_construction=200 and the measured
6GiB maintenance/five-worker budget, and keeps graph, physical seal and complete
readback separate. A native batch is bound to its actual sealed content rather
than claiming that native revisions belong to a provider generation. Current
claim/publication admission is checked before each phase and again before its
commit. No acceptance, active pointer or completed queue result is created.
