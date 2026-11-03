# Prepared native publisher

`publisher/` is an explicit third deployment, with its own lock and direct local
dependencies on both first-party packages. The standalone ingestion package
retains its own lock and imports no API modules. This bridge deliberately reuses
the source writer's existing SQL-only transaction callback and the API's native
capture, navigation, publication and queue contracts. It does not duplicate those
contracts in ingestion or dynamically attach an unpinned API checkout.

The operator supplies a complete `native-prepared-paper/1.0.0` JSON file containing
`source` (`arxiv` or `aps`), `metadata`, `chunks`, `materials`, and `inputs` keyed by
the actual evidence kinds. Each chunk contains its real complete vector and
embedding provenance. Each present evidence kind has one retained input with
relative path, source URI, media type, actual parser/chunker versions, expected
byte count and expected SHA256. Optional arXiv `ingestion_capture` remains the
existing diagnostic envelope; an APS input can specify `related_paper_id`.

The archive root is a separate operator-controlled absolute CLI argument. A
stable bounded prepared file and every retained representation are read in full.
The input observation proves those representation bytes, without granting
source rights, authenticating publisher delivery or accepting scientific data.
Different abstract/full-text/structured representations receive distinct input
receipts and are combined into one complete paper publication. APS original
passages are refused; authorized abstract/derived units remain supported.

```sh
cd publisher
uv sync --frozen
RETRIEVAL_BACKEND=pgvector uv run --frozen sclib-publish-native \
  --prepared /operator/prepared-paper.json \
  --archive-root /operator/retained-inputs --logical-index sclib-main
```

The default is a real transactional preview: paper/chunks, evidence, embedding
receipts, input/native revisions, navigation, publication seal and outbox job are
all rolled back together. `--apply` commits only after every step succeeds. Any
failure rolls the entire paper write back. The exact application schema must
already be admitted; the publisher performs no migration or privilege changes.
The explicit native callback also preserves existing chunk creation timestamps
and identities, removes omitted mutable chunks, and refuses cross-paper ID
collisions. This keeps identical input replays on the same native publication;
old source-writer callers retain their existing replacement behavior.

The command performs no download, model call, Google ANN write, active-pointer
change or archive deletion. Its result records a complete queued publication;
it does not mark the queue job published or grant quality acceptance. Provider
preparation and batch graph construction are separate workers. No existing
ingestion schedule is resumed by this package. Actual-paper end-to-end replay,
signed deployment and the full worker/acceptance cycle remain release gates.

The accompanying [batch worker](PGVECTOR_NATIVE_BATCH.md) supplies bounded
selection, expiring claims, durable content/vector preparation and actual
activation observation. Full-corpus host budgeting remains a separate guard.
