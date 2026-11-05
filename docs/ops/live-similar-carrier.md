# Live graph carrier

`RETRIEVAL_USE_SIMILAR_CARRIER=true` selects live traversal of a private copy of
the current sealed HNSW graph. The default remains false. It cannot be combined
with `RETRIEVAL_USE_SIMILAR_FRONTIERS=true`.

The same switch also selects the carrier for Search and Ask semantic candidates.
Those readers retain their own `ef_search=1000` and 1024-candidate frontier;
they do not inherit Similar's smaller budget. Year and revision filters are
resolved against the authoritative heap before admitting each frontier prefix,
and filtered roots trigger bounded continuation of the same graph cursor. Rare
year cohorts keep the existing exact-scoring path and 200000-row ceiling. All
traversal and final authoritative distance ranking share the original two-second
statement budget inside the three-second queue/connection/query budget. The
existing Search/Ask coordinator still applies rights, currentness, hydration,
ranking and final response checks.

This path does not require precomputed per-paper neighbors. Each request keeps
all currently eligible source vectors, the full revision exclusions, the 257-row
native candidate frontier and the original final ranking. The authoritative
database resolves every physical candidate and computes the distances. Existing
source/target rights, currentness, grouping and the fresh final snapshot remain
in `content_similarity.py`.

The complete 1–20 source inventory shares one 2-second traversal/ranking deadline
inside the existing 3-second queue/connection/query budget. It holds one of the
four database-wide SQL permits. There are no per-source retry loops, independent
source deadlines or partial-result responses. Missing physical roots or a
changed graph fail the entire request. Small eligible cohorts retain exact SQL
scoring.

## Release and provisioning

1. Build and sign the API with `models/similar_carrier_admission.json`. Both the
   primary and rollback graph entries bind the accepted content/policy, physical
   heap and index identities, every segment digest, PostgreSQL image digest and
   the qualified native reader digest. Changes to these identities require a new
   release; environment variables cannot admit alternative bytes.
2. Provision only the required graph using the existing bounded native-RAM
   capture/staging procedure. Verify the complete source and independent staged
   segment hashes against the **signed API admission**, including order and
   lengths. Verify the actual helper and image digests. Retain source captures,
   scientific data and failure receipts. The carrier must not mount authority
   PGDATA or copy the authoritative heap.
3. Keep the qualified PG 16.13/vector 0.8.7 Unix-socket-only empty-heap carrier,
   restricted `sclib_frontier_scan` role and existing resource limits. Do not
   expose a TCP port. The API sees only the read-only socket directory at
   `/run/sclib/similar-carrier/<build UUID>`; it receives no carrier administrative
   credentials.
4. After independent staged-byte verification, pass
   `services.similar_live_carrier.binding_payload(admission['builds'][build])`
   as `scope_json` to the existing carrier `install-reader.sql`, and pass the
   admitted extent as `graph_bytes`. This receipt binds the verified index,
   helper and engine to the signed release. A legacy scope-only binding is
   deliberately rejected by the live API.
5. Start the API with the carrier option selected. Normal content readiness
   preparation, the current authority/physical witness and the private binding
   must all pass. `/ready` also checks the live carrier. A missing or mismatched
   socket is unavailable; it never silently falls back to Google or the slow
   candidate path.

Retain the 210 GiB disk floor plus the measured backup/artifact peak, 6 GiB host
available-memory floor and the existing PostgreSQL and carrier cgroup guards.
Cold graph loading is an explicit operator stage before traffic, never request
work. A change of graph requires its independently verified carrier to be ready
before activating its readers. Admission of both graphs does not assert that
both are resident or ready.

The focused tests cover source-prefix/exclusion preservation, complete input
validation before SQL, manifest mismatch, shared deadlines, cancellation and
live source/target governance. Private response parity and production admission
remain separate evidence. Neither this switch nor its tests authorizes a public
percentage, changes observation thresholds or permits retiring retained Google
serving early.
