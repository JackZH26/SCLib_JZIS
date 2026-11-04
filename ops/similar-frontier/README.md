# Offline Similar graph reader

The bounded builder accepts an optional `--carrier-socket DIRECTORY`. It walks a private copy of one sealed HNSW index using the pgvector access method. A repeatable-read transaction on the authoritative database resolves physical row IDs, applies the full revision exclusion list and computes the final distances. A missing physical row stops the slice. Every completed source uses the existing SQLite checkpoint transaction and resumes through the existing build cursor.

## Prepare a carrier

1. Pin the accepted event, content, policy, source heap, index and their physical file identities. Under a bounded lock, capture all clean index segments on the source host and record the segment lengths and SHA-256 hashes. Abort on changed identity, a competing lock waiter, backup activity or resource pressure. Keep the corpus and graph on the authorized host.
2. Start a private PG 16.13 / pgvector 0.8.7 cluster on a restricted Unix socket directory at port 5542 with `listen_addresses=''`. Allow the operator and dedicated reader only. Create the `vector` extension and `sclib_private_carrier.carrier` as an empty heap with a `vector(768)` column. Create `sclib_private_carrier.sealed_hnsw` on that column with `vector_cosine_ops`, `m=32` and `ef_construction=200`.
3. Stop the private cluster cleanly, stage a writable private copy of the segments at its index paths, and independently read back every segment against the trusted capture. Preserve source file identities throughout staging and use. Keep the authority's PGDATA outside the carrier container.
4. Build the helper for the exact engine architecture using this directory's Dockerfile. Pin the qualified helper bytes and mount the library read-only at `$(pg_config --pkglibdir)/sclib_frontier_reader.so` inside the private cluster. After startup apply `install-reader.sql` as the private cluster owner with psql variables `scope_json` (the authoritative builder's complete graph scope) and `graph_bytes` (the verified source extent).
5. Run `scripts/build_similar_frontier.py` with the usual accepted event, build, content, slice size, interval and checkpoint arguments, plus the private socket. Use a read-only authority connection, enforce the local backup reserve and stop on guard failures. Keep primary and standby captures, bindings and checkpoints separate.

Publication still requires complete coverage of the sealed inventory and digest admission for both artifacts. The online service consumes the published SQLite files.
