# Native publication outbox

Schema0116 adds four private relations: immutable jobs, a per-job mutable fence,
immutable expiring claims and immutable attempt results. Jobs reference complete
sealed native publications, without copying their vectors or original text.
The database assigns ordering and observed timestamps. Producer-supplied order
values cannot override that ordering; gaps have no semantic meaning.

`capture_and_enqueue` observes the retained parser input, captures current native
revisions with their real embedding receipts, seals the complete paper inventory
and enqueues it in the caller's existing transaction. It commits nothing. A
failure rolls back the entire capture/outbox savepoint; source writers must also
fail their enclosing paper/chunk write. Replays preserve exact retained records.
Enqueue admission checks the current complete chunk inventory, source snapshot,
current evidence links, native record hashes and retained publication seal.

Workers claim a job with a distinct UUID and explicit worker label. Leases last
30–14,400 seconds, default7,200 seconds; at most100 attempts are admitted. Commit
the claim before graph, provider or filesystem work. A retry result releases the
claim early. After expiration another worker can claim it, while an old token
cannot finish. The fence performs a real row update, so stale repeatable-read
transactions cannot ignore a concurrently committed claim. Pending pages use
`FOR UPDATE SKIP LOCKED`, bounded to100 jobs, and claim/outcome lookups are indexed.

`retry` stores a closed error category. `superseded` requires an actual later job
for the same paper and logical index; it preserves both source publications.
`published` requires a real current v2 activation containing exactly that paper's
complete native publication. A legacy activation or a candidate build cannot
complete the job. None of the queue operations creates an acceptance, switches
an active pointer, grants source rights or marks scientific review complete.

Lease timestamps are hashed in canonical UTC, independently of the reader's
session timezone. Empty downgrade preserves prior data/functions; any retained
queue row prevents downgrade. Reverting an application must keep this history.

The separate `sclib_retrieval_producer` and `sclib_retrieval_queue_worker` group
roles are NOLOGIN groups provisioned by the operator. The schema grants only
the four new relations and new ordering sequence. It does not modify privileges
on older source tables, grant DDL, create logins or make either group a retrieval
publisher. Existing source-write/build identities need their already-reviewed
source permissions plus the appropriate queue group. An operator creating the
groups after migration must explicitly apply the model's `grants()` statements.

This component supplies the transactional outbox and resumable claim protocol.
The independently packaged ingestion deployment still needs its explicit locked
adapter, worker/batch construction, source-retention configuration and actual
new/corrected-paper replay. It remains paused. No import of API modules has been
added to that separate package and no Google writer has been re-enabled.
Synthetic transaction/recovery tests are not actual-paper or deployment evidence.
